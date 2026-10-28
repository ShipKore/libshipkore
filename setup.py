#!/usr/bin/env python

"""The setup script."""

from setuptools import setup, find_packages

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = [
    "Click>=8.0.3",
    "beautifulsoup4>=4.10.0",
    "python-dateutil>=2.8.2",
    "requests>=2.27.1",
    "pydantic>=2.12,<3",
    "parsel>=1.6.0",
    "class-registry>=2.1.2",
]

setup_requirements = [
    "pytest-runner",
]

test_requirements = [
    "pytest>=3",
]

setup(
    author="Innerkore",
    author_email="admin@innerkore.com",
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    description="Shipkore tracking library and CLI",
    entry_points={
        "console_scripts": [
            "libshipkore=libshipkore.cli:main",
            "libshipkore-mcp=libshipkore.mcp_server.__main__:main",
        ],
    },
    install_requires=requirements,
    extras_require={
        # SQLAlchemyStorage: Postgres, MySQL and other SQL databases
        "sql": ["sqlalchemy>=1.4"],
        # S3FileStore: AWS S3, MinIO, R2, Spaces and other S3-compatible stores
        "s3": ["boto3>=1.26"],
        # the MCP server for AI agents: the libshipkore-mcp command
        "mcp": ["mcp>=2.3,<3"],
    },
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="libshipkore",
    name="libshipkore",
    packages=find_packages(include=["libshipkore", "libshipkore.*"]),
    setup_requires=setup_requirements,
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/shipkore/libshipkore",
    version="0.5.0",
    zip_safe=False,
)
