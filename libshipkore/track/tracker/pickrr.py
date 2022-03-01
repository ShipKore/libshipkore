from ..common.basetrackservice import BaseTrackService, track_registry
import requests
from ..models.model import StatusChoice


@track_registry.register("pickrr")
class Pickrr(BaseTrackService):
    def status_code_mapper(self, status):
        """
        docstring
        """
        status_mapper = {
            "OP": StatusChoice.InfoReceived.value,
            "OM": StatusChoice.InfoReceived.value,
            "OC": StatusChoice.Exception.value,
            "PP": StatusChoice.InTransit.value,
            "OD": StatusChoice.InTransit.value,
            "OT": StatusChoice.InTransit.value,
            "SHP": StatusChoice.InTransit.value,
            "OO": StatusChoice.OutForDelivery.value,
            "NDR": StatusChoice.OutForDelivery.value,
            "DL": StatusChoice.Delivered.value,
            "RTO": StatusChoice.ReverseInTransit.value,
            "RTO-OT": StatusChoice.ReverseInTransit.value,
            "RTO-OO": StatusChoice.ReverseOutForDelivery.value,
            "RTP": StatusChoice.ReverseDelivered.value,
            "RTD": StatusChoice.ReverseDelivered.value,
        }
        return status_mapper.get(status, StatusChoice.Exception.value)

    def __init__(self, waybill, *args, **kwargs):
        super().__init__(waybill, "pickrr", *args, **kwargs)

    """
    This method will populate self.raw_data
    """

    def _fetch(self):
        self.raw_data = requests.get(
            f"https://cfapi.pickrr.com/plugins/tracking/?tracking_id={self.waybill}"
        ).json()
        # print(self.raw_data)

    def _transform_checkpoint(self, scan):
        checkpoint = {
            "slug": self.provider,
            "city": scan.get("status_location"),
            "location": scan.get("status_location"),
            "country_name": "India",
            "country_iso3": "IND",
            "status": self.status_code_mapper(scan.get("status_name", "")),
            "substatus": scan.get("status_body", ""),
            "checkpoint_time": scan.get("status_time", ""),
            "state": None,
            "zip": None,
        }

        return checkpoint

    """
    This method will convert self.raw_data to self.data
    """

    def _transform(self):
        waybill_data = self.raw_data
        data = {
            "waybill": self.waybill,
            "provider": self.provider,
            "status": self.status_code_mapper(
                waybill_data.get("status", {}).get("current_status_type", "")
            ),
            "substatus": waybill_data.get("status", {}).get("current_status_body", ""),
            "estimated_date": waybill_data.get("edd_stamp"),
            "package_type": waybill_data.get("dispatch_mode"),
            "destination": waybill_data.get("info").get("destination"),
            "product": waybill_data.get("product_name"),
            "receiver_name": "",
        }
        checkpoints = []
        for scan in waybill_data.get("track_arr", [])[::-1]:
            for scan2 in scan.get("status_array", [])[::-1]:
                scan2["status_name"] = scan["status_name"]
                checkpoints.append(self._transform_checkpoint(scan2))

        data["checkpoints"] = checkpoints

        self.data = data
        return data
