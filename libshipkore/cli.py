"""Console script for libshipkore."""
import sys
import click
from libshipkore.libshipkore import get_track_data

@click.command()
@click.option('--provider', prompt='Provider', help='Courier partner')
@click.option('--waybill', prompt='Waybill',
              help='Waybill or tracking number provided by provider.')
def main(provider, waybill):
    """Console script for libshipkore."""
    result = get_track_data(provider, waybill)
    print (result)
    return result


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
