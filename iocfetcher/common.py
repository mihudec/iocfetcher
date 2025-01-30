import re
import ipaddress
import time
import json


from iocfetcher.config import FeedConfig, FeedFormat, IoCTypes, IoCCategories
from iocfetcher.logger import get_logger

from typing import Any, Generator, Union, Iterable, List, Tuple, Dict

LOGGER = get_logger(name="IoC Fetcher", level=10)


REGEX_IP_LINE = re.compile(pattern="^(?:\d{1,3}\.){3}(?:\d{1,3})$", flags=re.MULTILINE)
REGEX_IPMASK_LINE = re.compile(pattern="^(?:\d{1,3}\.){3}(?:\d{1,3})(?:\/\d{1,2})$", flags=re.MULTILINE)
REGEX_IPMASKOPT_LINE = re.compile(pattern="^(?:\d{1,3}\.){3}(?:\d{1,3})(?:\/\d{1,2})?$", flags=re.MULTILINE)

REGEX_IP = re.compile(pattern="(?:\d{1,3}\.){3}(?:\d{1,3})")
REGEX_IPMASK = re.compile(pattern="(?:\d{1,3}\.){3}(?:\d{1,3})(?:\/\d{1,2})")
REGEX_IPMASKOPT = re.compile(pattern="(?:\d{1,3}\.){3}(?:\d{1,3})(?:\/\d{1,2})?")


REGEX_DOMAIN_LINE = re.compile(r'^\b(?!(?:\d{1,3}\.){3}\d{1,3}\b)(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{2,63})+\b$', flags=re.MULTILINE)
REGEX_DOMAIN = re.compile(r'\b(?!(?:\d{1,3}\.){3}\d{1,3}\b)(?!-)[A-Za-z0-9-]{1,63}(?:\.(?!-)[A-Za-z0-9-]{2,63})+\b')

REGEX_HASH = re.compile(r'\b(?:([a-fA-F0-9]{64})|([a-fA-F0-9]{40})|([a-fA-F0-9]{32}))\b')
REGEX_MD5 = re.compile(r'\b[a-fA-F0-9]{32}\b')
REGEX_SHA1 = re.compile(r'\b[a-fA-F0-9]{40}\b')
REGEX_SHA256 = re.compile(r'\b[a-fA-F0-9]{64}\b')
REGEX_SHA512 = re.compile(r'\b[a-fA-F0-9]{128}\b')
REGEX_URL = re.compile(r'\b((http|https|ftp):\/\/)?((\d{1,3}\.){3}\d{1,3}|[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})(:[0-9]{1,5})?\/[^\s]*\b')

class EctiJsonEncoder(json.JSONEncoder):

    def default(self, o):
        if isinstance(o, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            return str(o)
        if isinstance(o, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            return str(o)
        if isinstance(o, (ipaddress.IPv4Interface, ipaddress.IPv6Interface)):
            return str(o)
        return super().default(o)

def jdump(data: Union[Dict, List]) -> str:
    return json.dumps(data, cls=EctiJsonEncoder, indent=2)

def log_execution_time(func):
    """
    Decorator to measure and log the execution time of a function.
    """
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        LOGGER.debug(f"Execution time of {func.__name__}: {execution_time:.6f} seconds")
        return result
    return wrapper

def validate_lines(lines, regex: re.Pattern = None) -> Generator[str, None, None]:
    if not regex:
        for line in lines:
            if line.startswith("#") or not line.strip():
                continue
            yield line
    else:
        for line in lines:
            m = regex.match(line)
            if m:
                yield m.group(0)
            else:
                LOGGER.debug(f"Line '{line}' did not match pattern '{regex.pattern}'")

def search_lines(lines, regex: re.Pattern) -> Generator[str, None, None]:
    for line in lines:
        m = regex.search(line)
        if m:
            yield m.group(0)

def search_text(text, regex: re.Pattern) -> Generator[str, None, None]:
    for m in regex.finditer(text):
        yield m.group(0)



def parse_ip_network(ip_str: str) -> Union[ipaddress.IPv4Network, ipaddress.IPv6Network, None]:
    """
    Parses an IP string and returns an IPv4 or IPv6 network object.
    If the input is invalid, returns None.

    Args:
        ip_str (str): The input string representing an IP address or network.

    Returns:
        Union[ipaddress.IPv4Network, ipaddress.IPv6Network, None]: 
        Parsed IP network object, or None if parsing fails.
    """
    try:
        # Check if the string contains a subnet mask
        if '/' in ip_str:
            # Allow host bits for both IPv4 and IPv6
            return ipaddress.ip_network(ip_str)
        else:
            # Assume it's a single IP and add the default prefix (/32 for IPv4, /128 for IPv6)
            return ipaddress.ip_network(f"{ip_str}/32" if ':' not in ip_str else f"{ip_str}/128")
    except ValueError as e:
        # Handle 'host bits set' case
        if 'host bits set' in str(e):
            try:
                return ipaddress.ip_interface(ip_str).network
            except ValueError:
                return None  # Invalid IP format
    except Exception:
        # Raise unexpected exceptions
        raise
    return None  # If all else fails


def read_ip(source: Iterable) -> Generator[Union[ipaddress.IPv4Network, ipaddress.IPv6Network], None, None]:
    for line in source:
        yield parse_ip_network(line)



@log_execution_time
def summarize_subnets(subnets: Iterable[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]) -> Tuple[List[ipaddress.IPv4Network], List[ipaddress.IPv6Network], int]:

    subnets_v4 = list()
    subnets_v6 = list()
    length_input = 0

    for subnet in subnets:
        length_input += 1
        if subnet.version == 4:
            subnets_v4.append(subnet)
        if subnet.version == 6:
            subnets_v6.append(subnet)

    subnets_v4_sum = list(ipaddress.collapse_addresses(subnets_v4))
    subnets_v6_sum = list(ipaddress.collapse_addresses(subnets_v6))

    return subnets_v4_sum, subnets_v6_sum, length_input

def process_feed_data(fetch_results: List[Tuple[FeedConfig, Any]]):
    results = {}

    for source, _ in fetch_results:
        for t in [x.value for x in source.types]:
            if t not in results.keys():
                results[t] = {}
            for c in [x.value for x in source.categories]:
                if c not in results[t].keys():
                    results[t][c] = set()

    for source, data in fetch_results:

        if len(data) == 0:
            continue

        if IoCTypes.IP in source.types:
            if source.format == FeedFormat.TEXT_LINES:
                ip_list = list(read_ip(validate_lines(data, regex=REGEX_IPMASKOPT_LINE)))
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.IP.value][c].update(ip_list)
            elif source.format == FeedFormat.STIX_PATTER:
                ip_list = list(read_ip(search_lines(data, regex=REGEX_IPMASKOPT)))
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.IP.value][c].update(ip_list)
            elif source.format == FeedFormat.TEXT:
                ip_list = list(read_ip(search_text(data, regex=REGEX_IPMASKOPT_LINE)))
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.IP.value][c].update(ip_list)
        
        if IoCTypes.DOMAIN in source.types:
            if source.format == FeedFormat.TEXT_LINES:
                domains = validate_lines(data, regex=REGEX_DOMAIN_LINE)
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.DOMAIN.value][c].update((x.lower() for x in domains))
            elif source.format == FeedFormat.STIX_PATTER:
                domains = search_lines(data, regex=REGEX_DOMAIN)
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.DOMAIN.value][c].update((x.lower() for x in domains))
            elif source.format == FeedFormat.TEXT:
                domains = search_text(data, regex=REGEX_DOMAIN_LINE)
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.DOMAIN.value][c].update((x.lower() for x in domains))
        
        if IoCTypes.HASH in source.types:
            if source.format == FeedFormat.TEXT_LINES:
                hashes = validate_lines(data, regex=REGEX_HASH)
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.HASH.value][c].update((x.lower() for x in hashes))
            elif source.format == FeedFormat.STIX_PATTER:
                hashes = search_lines(data, regex=REGEX_HASH)
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.HASH.value][c].update((x.lower() for x in hashes))
            elif source.format == FeedFormat.TEXT:
                hashes = search_text(data, regex=REGEX_HASH)
                for c in [x.value for x in source.categories]:
                    results[IoCTypes.HASH.value][c].update((x.lower() for x in hashes))
        

    # Remove Excluded Values
    for t in results.keys():
        if IoCCategories.EXCLUDE.value in results[t].keys():
            if IoCCategories.BLOCK in results[t].keys():
                results[t][IoCCategories.BLOCK.value] -= results[t][IoCCategories.EXCLUDE.value]
            if IoCCategories.IOC in results[t].keys():
                results[t][IoCCategories.IOC.value] -= results[t][IoCCategories.EXCLUDE.value]


    # Summarize IP Addresses
    if IoCTypes.IP.value in results.keys():
        for c in results[IoCTypes.IP.value].keys():
            if c == IoCCategories.EXCLUDE.value:
                continue
            ipv4, ipv6, length_input = summarize_subnets(results[IoCTypes.IP.value][c])
            results[IoCTypes.IP.value][c] = ipv4 + ipv6

    # Convert Sets to Sorted Lists
    for t in results.keys():
        for c in results[t].keys():
            results[t][c] = sorted(results[t][c])

    return results