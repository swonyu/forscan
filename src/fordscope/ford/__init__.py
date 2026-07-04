"""Ford-specific enhanced diagnostics — addressing, modules, As-Built (later)."""

from .addressing import (
    AddressPair,
    TESTER_ADDRESS,
    FUNCTIONAL_TARGET_ADDRESS,
    OBD_FUNCTIONAL_REQUEST_ID,
    TYPICAL_FORD_MODULES,
    eleven_bit_module,
    legislated_obd_pair,
    extended_module,
    extended_functional_request_id,
    ford_module,
)
from .asbuilt import (
    AsBuiltCoder,
    InMemoryBackupStore,
    FileBackupStore,
    AsBuiltError,
    BackupRequiredError,
    VerificationError,
    NoBackupError,
)
from .asbuilt_format import AsBuiltBlock, parse_block, compute_checksum
from .features import FeatureDefinition, FeatureCoder, EXAMPLE_FEATURES

__all__ = [
    "AddressPair",
    "TESTER_ADDRESS",
    "FUNCTIONAL_TARGET_ADDRESS",
    "OBD_FUNCTIONAL_REQUEST_ID",
    "TYPICAL_FORD_MODULES",
    "eleven_bit_module",
    "legislated_obd_pair",
    "extended_module",
    "extended_functional_request_id",
    "ford_module",
    "AsBuiltCoder",
    "InMemoryBackupStore",
    "FileBackupStore",
    "AsBuiltError",
    "BackupRequiredError",
    "VerificationError",
    "NoBackupError",
    "AsBuiltBlock",
    "parse_block",
    "compute_checksum",
    "FeatureDefinition",
    "FeatureCoder",
    "EXAMPLE_FEATURES",
]
