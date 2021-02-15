"""Console script for libshipkore."""
import sys
import click
from libshipkore.libshipkore import get_track_data, get_providers

@click.group()
def track_cli():
    pass

@click.group()
def providers_cli():
    pass

@track_cli.command()
@click.option('--provider', prompt='Provider', help='Courier partner')
@click.option('--waybill', prompt='Waybill',
              help='Waybill or tracking number provided by provider.')
def track(provider, waybill):
    """Console script for libshipkore."""
    result = get_track_data(provider, waybill)
    print (result)
    return result

@providers_cli.command()
def providers():
    """Console script for libshipkore."""
    result = get_providers()
    print (result)
    return result

main = click.CommandCollection(sources=[track_cli, providers_cli])

if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
