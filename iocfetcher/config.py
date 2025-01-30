import pathlib
import yaml
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, ConfigDict, field_validator, StringConstraints
from typing import ClassVar, Dict, List, Union, Optional, Annotated

BASE_DIR = pathlib.Path("/app/")
BASE_CONFIG_PATH = BASE_DIR.joinpath("config.yaml")

class ConfigBase(BaseModel):

    _default_config_path: ClassVar = BASE_CONFIG_PATH

    @classmethod
    def from_config_file(cls, file: pathlib.Path = None):
        if file is None:
            file = cls._default_config_path
        if not isinstance(file, pathlib.Path):
            file = pathlib.Path(file)
        text = file.read_text()
        data = yaml.safe_load(text)
        config = cls.model_validate(data)
        return config
    
class IoCTypes(str, Enum):
    IP = "ip"
    IPv4 = "ipv4"
    IPv6 = "ipv6"
    IPNET = "ip-net"
    IPv4NET = "ipv4-net"
    IPv6NET = "ipv6-net"
    DOMAIN = "domain"
    HASH = "hash"

class IoCCategories(str, Enum):
    IOC = "ioc"
    BLOCK = "block"
    EXCLUDE = "exclude"

class FeedFormat(str, Enum):
    TEXT_LINES = "lines"
    TEXT = "text"
    STIX_PATTER = "stix-pattern"

ScopeString = Annotated[str, StringConstraints(to_lower=True)]


class FeedConfig(ConfigBase):
    # model_config = ConfigDict(use_enum_values=True)

    url: HttpUrl = Field(default=..., )
    format: FeedFormat
    categories: List[IoCCategories] = Field(default=..., )
    types: List[IoCTypes] = Field(default=..., )
    scopes: Optional[List[ScopeString]] = Field(default=["COMMON"])
    headers: Optional[Dict[str, str]] = Field({})

class CacheConfig(ConfigBase):
    expiration: Optional[int] = 60
    max_age: Optional[int] = 300

class ServerConfig(ConfigBase):
    cache: Optional[CacheConfig] = Field(default_factory=CacheConfig)
    log_verbosity: Optional[int] = 20

class Config(ConfigBase):
    server: Optional[ServerConfig] = Field(default_factory=ServerConfig)
    sources: List[FeedConfig]


    def get_sources(self, typ: str, cat: str, scopes: List[str] = ['COMMON']) -> List[FeedConfig]:
        typ = IoCTypes(typ)
        cat = IoCCategories(cat)
        scopes = [x.lower() for x in scopes]
        return [
            source for source in self.sources 
            if typ in source.types and cat in source.categories and (any(x in source.scopes for x in scopes))
        ]

