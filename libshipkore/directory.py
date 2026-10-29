"""
What the library knows about each courier, beyond how to call it: who they
are, how to reach them and where they operate.

Every fact about a courier (website, phone, email, categories, countries,
service areas) comes from the courier's own public pages and is recorded with
the pages it came from and the date it was read, because phone numbers and
network sizes go stale. A courier we have not researched has none of these;
nothing is filled in from memory. Entries live in data/carriers.json and are
validated here when loaded, so a typo fails loudly.

`countries.primary` is where the courier runs its own network; `secondary` is
where it reaches through partners or an international service, only when the
courier names the countries. When it only says "220+ countries", that goes in
`service_areas` as the courier's own claim.
"""
import re
from datetime import date
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator, model_validator

from libshipkore.common.models import Model

CATEGORIES = (
    "express_parcel",   # door-to-door parcels and documents
    "ecommerce",        # built around online sellers (COD, returns, marketplaces)
    "aggregator",       # sells several couriers' services through one account
    "hyperlocal",       # same-city, on-demand delivery
    "ptl_freight",      # part-truckload / LTL freight
    "ftl_freight",      # full-truckload freight
    "warehousing",      # storage and fulfilment
    "international",    # cross-border parcels or freight
    "postal",           # national postal operator
)
COUNTRY = re.compile(r"[A-Z]{2}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\+?[\d][\d\s\-]{5,18}\d")


class Strict(Model):
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)


class Phone(Strict):
    number: str
    label: str  # what it is for, in the courier's words: "customer service", "order queries"

    @field_validator("number")
    @classmethod
    def looks_like_a_number(cls, value):
        if not PHONE.fullmatch(value):
            raise ValueError(f"not a phone number: {value!r}")
        return value


class Email(Strict):
    address: str
    label: str  # "customer support", "sales", "escalation"

    @field_validator("address")
    @classmethod
    def looks_like_an_address(cls, value):
        if not EMAIL.fullmatch(value):
            raise ValueError(f"not an email address: {value!r}")
        return value


class Countries(Strict):
    primary: List[str] = Field(default_factory=list)    # ISO 3166-1 alpha-2
    secondary: List[str] = Field(default_factory=list)

    @field_validator("primary", "secondary")
    @classmethod
    def iso_codes(cls, values):
        bad = [v for v in values if not COUNTRY.fullmatch(v)]
        if bad:
            raise ValueError(f"country codes are two capital letters, got {bad}")
        return values


class Provenance(Strict):
    sources: List[str]   # the pages the facts were read from
    verified_on: date

    @field_validator("sources")
    @classmethod
    def https_pages(cls, values):
        if not values or any(not v.startswith(("https://", "http://")) for v in values):
            raise ValueError("sources must be URLs of the courier's own pages")
        return values


class Carrier(Strict):
    slug: str
    name: str
    country: Optional[str] = None            # where the courier is based
    supported: bool = False                  # tracking is built
    note: Optional[str] = None               # why not, or a caveat
    waybill_pattern: Optional[str] = None
    website: Optional[str] = None
    phones: List[Phone] = Field(default_factory=list)
    emails: List[Email] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    countries: Optional[Countries] = None
    service_areas: List[str] = Field(default_factory=list)
    profile: Optional[Provenance] = None

    @field_validator("country")
    @classmethod
    def iso_country(cls, value):
        if value is not None and not COUNTRY.fullmatch(value):
            raise ValueError(f"country is two capital letters, got {value!r}")
        return value

    @field_validator("website")
    @classmethod
    def https_website(cls, value):
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("website must be a URL")
        return value

    @field_validator("categories")
    @classmethod
    def known_categories(cls, values):
        bad = sorted(set(values) - set(CATEGORIES))
        if bad:
            raise ValueError(f"unknown categories {bad}; use {list(CATEGORIES)}")
        return values

    @model_validator(mode="after")
    def facts_need_a_source(self):
        facts = (self.website, self.phones, self.emails, self.categories,
                 self.countries, self.service_areas)
        if any(facts) and self.profile is None:
            raise ValueError(f"{self.slug}: profile facts need profile.sources and profile.verified_on")
        return self

    def operates_in(self, country):
        """True when the country is the courier's home or a primary or secondary country."""
        country = country.upper()
        listed = (self.countries.primary + self.countries.secondary) if self.countries else []
        return country in listed or self.country == country
