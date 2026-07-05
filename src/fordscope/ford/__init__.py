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
    CorruptBackupStoreError,
)
from .asbuilt_format import AsBuiltBlock, parse_block, compute_checksum
from .features import FeatureDefinition, FeatureCoder, EXAMPLE_FEATURES
from . import fusion_2016
from . import fusion_2016_asbuilt
from .fusion_2016_asbuilt import (
    AsBuiltFeatureRef,
    FUSION_2016_ASBUILT,
    additive_checksum,
    parse_hex_bytes,
    verify_full_line,
    AsBuiltLineCheck,
    features_at_block_line,
)
from . import asbuilt_catalog_view
from .asbuilt_catalog_view import (
    filter_features, format_catalog, CATALOG_CAVEAT, format_block_line_lookup,
)

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
    "CorruptBackupStoreError",
    "AsBuiltBlock",
    "parse_block",
    "compute_checksum",
    "FeatureDefinition",
    "FeatureCoder",
    "EXAMPLE_FEATURES",
    "fusion_2016",
    "fusion_2016_asbuilt",
    "AsBuiltFeatureRef",
    "FUSION_2016_ASBUILT",
    "additive_checksum",
    "parse_hex_bytes",
    "verify_full_line",
    "AsBuiltLineCheck",
    "features_at_block_line",
    "asbuilt_catalog_view",
    "filter_features",
    "format_catalog",
    "CATALOG_CAVEAT",
    "format_block_line_lookup",
]
