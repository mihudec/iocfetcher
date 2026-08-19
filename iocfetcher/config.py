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


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

ScopeString = Annotated[str, StringConstraints(to_lower=True)]


class FeedConfig(ConfigBase):
    # model_config = ConfigDict(use_enum_values=True)

    url: HttpUrl = Field(default=..., )
    format: FeedFormat
    categories: List[IoCCategories] = Field(default=..., )
    types: List[IoCTypes] = Field(default=..., )
    scopes: Optional[List[ScopeString]] = Field(default_factory=lambda: ["common"])
    headers: Optional[Dict[str, str]] = Field(default_factory=dict)
    refresh_after: int = Field(default=300, gt=0)
    max_stale: Optional[int] = Field(default=None, ge=0)
    retry_after: int = Field(default=60, gt=0)
    fetch_timeout: Optional[float] = Field(default=None, gt=0)

class CacheConfig(ConfigBase):
    expiration: Optional[int] = 60
    max_age: Optional[int] = 300

class ServerConfig(ConfigBase):
    cache: Optional[CacheConfig] = Field(default_factory=CacheConfig)
    log_verbosity: LogLevel = LogLevel.INFO
    fetch_timeout: Optional[int] = 30

    @field_validator("log_verbosity", mode="before")
    @classmethod
    def normalize_log_verbosity(cls, value):
        return value.lower() if isinstance(value, str) else value

class Config(ConfigBase):
    server: Optional[ServerConfig] = Field(default_factory=ServerConfig)
    sources: List[FeedConfig]


    def get_sources(self, typ: str, cat: str, scopes: List[str] = ['COMMON']) -> List[FeedConfig]:
        typ = IoCTypes(typ)
        cat = IoCCategories(cat)
        scopes = [x.lower() for x in scopes]
        sources = [
            source for source in self.sources 
            if typ in source.types and cat in source.categories and (any(x in source.scopes for x in scopes))
        ]
        excludes = [
            source for source in self.sources 
            if typ in source.types and IoCCategories('exclude') in source.categories and (any(x in source.scopes for x in scopes))
        ]
        return sources + excludes
