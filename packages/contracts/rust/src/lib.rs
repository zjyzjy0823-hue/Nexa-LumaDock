//! Studiolo Sync Protocol v3 — Rust contract types (strict serde models).
//!
//! Normative references:
//!
//! * `packages/contracts/sync-protocol-v3.md` — prose contract
//! * `packages/contracts/schema/sync-v3.schema.json` — machine-readable contract
//! * `packages/contracts/cases.json` — conformance cases shared by all validators
//!
//! Design rules enforced here (see the contract §1):
//!
//! * **camelCase only.** Every struct carries `rename_all = "camelCase"`.
//! * **No unknown fields.** Every struct is `deny_unknown_fields`; a payload that
//!   carries a field outside the whitelist is a protocol violation (`invalid_fields`).
//! * **Scalar formats are types, not comments.** `Uuid`, `IsoUtc`, `DecimalString`
//!   and friends validate on deserialization, so a malformed scalar can never reach
//!   business code as a `String`.
//! * **Cross-field rules live in typed invariants.** `ChangesResponse::validate`
//!   implements SR-5..SR-7; SR-3/SR-8 are enforced by the `Deserialize` impls of
//!   `Mutation`/`Change`; the §11.2 snapshot rules by `SnapshotEntity` and
//!   `SnapshotPage::validate`; SR-2 by [`parse_entity_data`].
//!
//! Deliberately stricter than the JSON Schema in four documented spots:
//!
//! 1. `IsoUtc` also range-checks month/day/hour/minute/second (the schema pattern is
//!    digit-only, so it would accept `2026-99-99T99:99:99Z`). Both zero-offset
//!    designators (`Z` and `+00:00`) are accepted, matching the schema; any other
//!    offset is rejected because the wire format is UTC-only.
//! 2. `MutationResult` rejects fields that do not belong to the `status` branch it
//!    carries, and requires `reason = invalid_id` on the early-rejected shape.
//! 3. `PersonalStateData` is `deny_unknown_fields` even though the schema omits
//!    `additionalProperties: false` for it; this type is the canonical strict view.
//! 4. `SnapshotPage`/`SnapshotEntity` enforce the §11.2 cross-field rules the schema
//!    cannot express: `cursor` is `null` exactly when `hasMore` is `false`, a
//!    tombstone is `deleted: true` + `data: null`, and `syncRevision` never exceeds
//!    `workspaceRevision`.
//!
//! Nothing here derives `Default` or `Option`-wraps a field that the schema marks
//! required — silently substituting a default is exactly the failure mode the
//! contract forbids.

#![forbid(unsafe_code)]

use serde::de::{self, DeserializeOwned};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::{Map, Value};
use std::fmt;
use std::str::FromStr;

/// `SYNC_PROTOCOL_VERSION` (`backend/app/sync/protocol.py`). Bumped only on a
/// breaking change, and v3 must stay served for at least one release cycle.
pub const SYNC_PROTOCOL_VERSION: u8 = 3;

/// Largest value the contract allows for `baseRevision` (`0 .. 2^63-1`).
const MAX_BASE_REVISION: u64 = i64::MAX as u64;

/// Listing order used by every "全部取值" assertion and by validation tooling.
pub const ENTITY_TYPE_COUNT: usize = 9;
/// `RejectionReason` is a closed set of 13 values (§3.3).
pub const REJECTION_REASON_COUNT: usize = 13;

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// A scalar failed its wire-format check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvalidValue {
    /// Newtype name, e.g. `"Uuid"`.
    pub type_name: &'static str,
    /// The offending value, verbatim (never truncated, never repaired).
    pub value: String,
    /// Why it was rejected.
    pub reason: String,
}

impl InvalidValue {
    fn new(type_name: &'static str, value: &str, reason: impl Into<String>) -> Self {
        Self {
            type_name,
            value: value.to_owned(),
            reason: reason.into(),
        }
    }
}

impl fmt::Display for InvalidValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "invalid {} `{}`: {}",
            self.type_name, self.value, self.reason
        )
    }
}

impl std::error::Error for InvalidValue {}

/// An entity `data` object did not match the payload schema for its `entityType`
/// (SR-2 ⇒ `rejected` / `invalid_data`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntityDataError {
    pub entity_type: EntityType,
    pub message: String,
}

impl fmt::Display for EntityDataError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "invalid data for `{}`: {}",
            self.entity_type.as_str(),
            self.message
        )
    }
}

impl std::error::Error for EntityDataError {}

/// A response-level invariant (§4.2, SR-5..SR-7) was violated.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractViolation {
    /// Rule id from `cases.json#semanticRules`, e.g. `"SR-6"`.
    pub rule: &'static str,
    pub detail: String,
}

impl ContractViolation {
    fn new(rule: &'static str, detail: impl Into<String>) -> Self {
        Self {
            rule,
            detail: detail.into(),
        }
    }
}

impl fmt::Display for ContractViolation {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} violated: {}", self.rule, self.detail)
    }
}

impl std::error::Error for ContractViolation {}

// ---------------------------------------------------------------------------
// Validated string newtypes
// ---------------------------------------------------------------------------

macro_rules! checked_string_newtype {
    ($(#[$doc:meta])* $name:ident, $check:expr) => {
        $(#[$doc])*
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            /// The validated wire representation.
            pub fn as_str(&self) -> &str {
                self.0.as_str()
            }

            /// Consume the newtype, keeping the validated string.
            pub fn into_inner(self) -> String {
                self.0
            }

            /// Validate then wrap. The only way to build the newtype.
            pub fn try_new(value: impl Into<String>) -> Result<Self, InvalidValue> {
                let value = value.into();
                let check: fn(&str) -> Result<(), String> = $check;
                check(value.as_str()).map_err(|reason| {
                    InvalidValue::new(stringify!($name), value.as_str(), reason)
                })?;
                Ok(Self(value))
            }
        }

        impl TryFrom<&str> for $name {
            type Error = InvalidValue;

            fn try_from(value: &str) -> Result<Self, InvalidValue> {
                Self::try_new(value)
            }
        }

        impl TryFrom<String> for $name {
            type Error = InvalidValue;

            fn try_from(value: String) -> Result<Self, InvalidValue> {
                Self::try_new(value)
            }
        }

        impl FromStr for $name {
            type Err = InvalidValue;

            fn from_str(value: &str) -> Result<Self, InvalidValue> {
                Self::try_new(value)
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(self.as_str())
            }
        }

        impl AsRef<str> for $name {
            fn as_ref(&self) -> &str {
                self.as_str()
            }
        }

        impl Serialize for $name {
            fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
                serializer.serialize_str(self.as_str())
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                let value = String::deserialize(deserializer)?;
                Self::try_new(value).map_err(de::Error::custom)
            }
        }
    };
}

fn check_uuid(value: &str) -> Result<(), String> {
    let bytes = value.as_bytes();
    if bytes.len() != 36 {
        return Err(format!(
            "expected 36 characters in 8-4-4-4-12 form, got {}",
            bytes.len()
        ));
    }
    for (index, byte) in bytes.iter().enumerate() {
        match index {
            8 | 13 | 18 | 23 => {
                if *byte != b'-' {
                    return Err(format!("expected `-` at index {index}"));
                }
            }
            _ => {
                if !matches!(byte, b'0'..=b'9' | b'a'..=b'f') {
                    return Err(format!(
                        "invalid character `{}` at index {index} (lowercase hex only)",
                        *byte as char
                    ));
                }
            }
        }
    }
    Ok(())
}

fn check_iso_utc(value: &str) -> Result<(), String> {
    // `YYYY-MM-DDTHH:MM:SS[.ffffff]` + a zero-offset designator: `Z` (preferred,
    // §1) or `+00:00` (what `iso_utc()` emits today). Any other offset is a
    // non-UTC instant and is rejected: the wire format is UTC-only.
    let body = match value.strip_suffix('Z') {
        Some(body) => body,
        None => match value.strip_suffix("+00:00") {
            Some(body) => body,
            None => {
                return Err("expected the `Z` or `+00:00` UTC designator at the end".to_owned());
            }
        },
    };

    let bytes = body.as_bytes();
    let len = bytes.len();
    if len != 19 && !(21..=26).contains(&len) {
        return Err(format!(
            "expected `YYYY-MM-DDTHH:MM:SS[.ffffff]` followed by `Z` or `+00:00` \
             (19 or 21..=26 chars before the designator), got {len}"
        ));
    }
    let expect_digits = |range: std::ops::Range<usize>| -> Result<(), String> {
        for index in range {
            if !bytes[index].is_ascii_digit() {
                return Err(format!(
                    "expected a digit at index {index}, found `{}`",
                    bytes[index] as char
                ));
            }
        }
        Ok(())
    };
    expect_digits(0..4)?;
    if bytes[4] != b'-' {
        return Err("expected `-` at index 4".to_owned());
    }
    expect_digits(5..7)?;
    if bytes[7] != b'-' {
        return Err("expected `-` at index 7".to_owned());
    }
    expect_digits(8..10)?;
    if bytes[10] != b'T' {
        return Err("expected `T` at index 10".to_owned());
    }
    expect_digits(11..13)?;
    if bytes[13] != b':' {
        return Err("expected `:` at index 13".to_owned());
    }
    expect_digits(14..16)?;
    if bytes[16] != b':' {
        return Err("expected `:` at index 16".to_owned());
    }
    expect_digits(17..19)?;
    if len != 19 {
        if bytes[19] != b'.' {
            return Err("expected `.` before the fractional seconds".to_owned());
        }
        expect_digits(20..len)?;
    }

    let number = |range: std::ops::Range<usize>| -> u32 {
        let mut total = 0_u32;
        for index in range {
            total = total * 10 + u32::from(bytes[index] - b'0');
        }
        total
    };
    let month = number(5..7);
    let day = number(8..10);
    let hour = number(11..13);
    let minute = number(14..16);
    // 60 is allowed: ISO 8601 leap second.
    let second = number(17..19);
    if !(1..=12).contains(&month) {
        return Err(format!("month `{month:02}` is out of range 01..=12"));
    }
    if !(1..=31).contains(&day) {
        return Err(format!("day `{day:02}` is out of range 01..=31"));
    }
    if hour > 23 {
        return Err(format!("hour `{hour:02}` is out of range 00..=23"));
    }
    if minute > 59 {
        return Err(format!("minute `{minute:02}` is out of range 00..=59"));
    }
    if second > 60 {
        return Err(format!("second `{second:02}` is out of range 00..=60"));
    }
    Ok(())
}

fn check_decimal_string(value: &str) -> Result<(), String> {
    // `^(0|[1-9]\d{0,11})(\.\d{1,2})?$` — money is a decimal *string*, never a number.
    let (integer_part, fraction_part) = match value.split_once('.') {
        Some((integer, fraction)) => (integer, Some(fraction)),
        None => (value, None),
    };
    if integer_part.is_empty() {
        return Err("missing integer part".to_owned());
    }
    if !integer_part.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err("integer part must be ASCII digits".to_owned());
    }
    if integer_part.len() > 1 && integer_part.starts_with('0') {
        return Err("integer part must not have a leading zero".to_owned());
    }
    if integer_part.len() > 12 {
        return Err(format!(
            "integer part has {} digits, at most 12 allowed (`Numeric(14,2)`)",
            integer_part.len()
        ));
    }
    if let Some(fraction) = fraction_part {
        if fraction.is_empty() {
            return Err("fractional part must have 1 or 2 digits".to_owned());
        }
        if fraction.len() > 2 {
            return Err(format!(
                "fractional part has {} digits, at most 2 allowed",
                fraction.len()
            ));
        }
        if !fraction.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err("fractional part must be ASCII digits".to_owned());
        }
    }
    Ok(())
}

fn check_http_url(value: &str) -> Result<(), String> {
    if value.len() < 8 {
        return Err(format!("length {} is below the minimum 8", value.len()));
    }
    if value.len() > 2048 {
        return Err(format!("length {} exceeds the maximum 2048", value.len()));
    }
    let rest = match value
        .strip_prefix("https://")
        .or_else(|| value.strip_prefix("http://"))
    {
        Some(rest) => rest,
        None => return Err("must start with `http://` or `https://`".to_owned()),
    };
    if rest.is_empty() {
        return Err("missing authority after the scheme".to_owned());
    }
    if rest.chars().any(char::is_whitespace) {
        return Err("must not contain whitespace".to_owned());
    }
    Ok(())
}

fn check_client_credential(value: &str) -> Result<(), String> {
    let secret = match value.strip_prefix("nc_live_") {
        Some(secret) => secret,
        None => return Err("must start with the `nc_live_` prefix".to_owned()),
    };
    if secret.len() < 40 {
        return Err(format!(
            "secret part has {} characters, at least 40 required",
            secret.len()
        ));
    }
    if !secret
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
    {
        return Err("secret part must be `[A-Za-z0-9_-]`".to_owned());
    }
    Ok(())
}

fn check_token_last4(value: &str) -> Result<(), String> {
    if value.len() != 4 {
        return Err(format!("expected exactly 4 characters, got {}", value.len()));
    }
    if !value.bytes().all(|byte| byte.is_ascii_alphanumeric()) {
        return Err("must be `[A-Za-z0-9]{4}`".to_owned());
    }
    Ok(())
}

fn check_non_empty(value: &str) -> Result<(), String> {
    if value.is_empty() {
        return Err("must not be empty".to_owned());
    }
    Ok(())
}

checked_string_newtype!(
    /// UUID v4 in canonical lowercase hyphenated form (§1: any other form ⇒ `invalid_id`).
    Uuid,
    check_uuid
);

checked_string_newtype!(
    /// ISO 8601 UTC timestamp: mandatory zero-offset designator (`Z`, or `+00:00`
    /// as `iso_utc()` emits today), optional 1..6 fractional digits. Non-zero
    /// offsets are rejected.
    IsoUtc,
    check_iso_utc
);

checked_string_newtype!(
    /// Money as a decimal string, at most 12 integer digits and 2 decimals.
    ///
    /// The schema pattern also admits `"0"`; the `gt=0` rule is a *service* rule
    /// (SR-2 ⇒ `rejected` / `invalid_data`), not a wire-format rule, hence not in the
    /// type. Use [`DecimalString::is_positive`] where the distinction matters.
    DecimalString,
    check_decimal_string
);

checked_string_newtype!(
    /// `nc_live_*` client credential. Returned exactly once by `POST /clients/enroll`.
    ClientCredential,
    check_client_credential
);

checked_string_newtype!(
    /// Last four characters of a client token, echoed for UI display.
    TokenLast4,
    check_token_last4
);

checked_string_newtype!(
    /// Absolute `http`/`https` URL, 8..=2048 bytes, no whitespace.
    HttpUrl,
    check_http_url
);

checked_string_newtype!(
    /// A string that must contain at least one character (`minLength: 1`).
    NonEmptyStr,
    check_non_empty
);

impl DecimalString {
    /// `false` for `"0"`, `"0.0"`, `"0.00"`; the contract requires `amount > 0`.
    pub fn is_positive(&self) -> bool {
        self.as_str()
            .bytes()
            .any(|byte| byte.is_ascii_digit() && byte != b'0')
    }
}

/// A string with a character-count bound, mirroring `minLength`/`maxLength`.
///
/// `MIN = 1` means "required and non-empty"; `MIN = 0` means "may be empty".
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct BoundedStr<const MIN: usize, const MAX: usize>(String);

impl<const MIN: usize, const MAX: usize> BoundedStr<MIN, MAX> {
    pub fn as_str(&self) -> &str {
        self.0.as_str()
    }

    pub fn into_inner(self) -> String {
        self.0
    }

    pub fn try_new(value: impl Into<String>) -> Result<Self, InvalidValue> {
        let value = value.into();
        let count = value.chars().count();
        if count < MIN || count > MAX {
            return Err(InvalidValue::new(
                "BoundedStr",
                value.as_str(),
                format!("length {count} is outside {MIN}..={MAX}"),
            ));
        }
        Ok(Self(value))
    }
}

impl<const MIN: usize, const MAX: usize> TryFrom<&str> for BoundedStr<MIN, MAX> {
    type Error = InvalidValue;

    fn try_from(value: &str) -> Result<Self, InvalidValue> {
        Self::try_new(value)
    }
}

impl<const MIN: usize, const MAX: usize> TryFrom<String> for BoundedStr<MIN, MAX> {
    type Error = InvalidValue;

    fn try_from(value: String) -> Result<Self, InvalidValue> {
        Self::try_new(value)
    }
}

impl<const MIN: usize, const MAX: usize> FromStr for BoundedStr<MIN, MAX> {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        Self::try_new(value)
    }
}

impl<const MIN: usize, const MAX: usize> fmt::Display for BoundedStr<MIN, MAX> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl<const MIN: usize, const MAX: usize> AsRef<str> for BoundedStr<MIN, MAX> {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl<const MIN: usize, const MAX: usize> Serialize for BoundedStr<MIN, MAX> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de, const MIN: usize, const MAX: usize> Deserialize<'de> for BoundedStr<MIN, MAX> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        Self::try_new(value).map_err(de::Error::custom)
    }
}

// ---------------------------------------------------------------------------
// Numeric newtypes
// ---------------------------------------------------------------------------

/// `protocolVersion`, pinned to 3. Any other value ⇒ `409 sync_protocol_mismatch`
/// upstream; here it simply fails to deserialize.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Default)]
pub struct ProtocolVersion(u8);

impl ProtocolVersion {
    pub const V3: ProtocolVersion = ProtocolVersion(SYNC_PROTOCOL_VERSION);

    pub fn get(self) -> u8 {
        self.0
    }

    pub fn try_new(value: u8) -> Result<Self, InvalidValue> {
        if value != SYNC_PROTOCOL_VERSION {
            return Err(InvalidValue::new(
                "ProtocolVersion",
                &value.to_string(),
                format!("only {SYNC_PROTOCOL_VERSION} is supported (no negotiation, no downgrade)"),
            ));
        }
        Ok(Self(value))
    }
}

impl fmt::Display for ProtocolVersion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl Serialize for ProtocolVersion {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_u8(self.0)
    }
}

impl<'de> Deserialize<'de> for ProtocolVersion {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = u8::deserialize(deserializer)?;
        Self::try_new(value).map_err(de::Error::custom)
    }
}

/// `baseRevision`, an integer in `0 ..= 2^63-1`. `0` means "this side believes the
/// row does not exist".
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct BaseRevision(u64);

impl BaseRevision {
    pub const ZERO: BaseRevision = BaseRevision(0);

    pub fn get(self) -> u64 {
        self.0
    }

    pub fn try_new(value: u64) -> Result<Self, InvalidValue> {
        if value > MAX_BASE_REVISION {
            return Err(InvalidValue::new(
                "BaseRevision",
                &value.to_string(),
                format!("must be <= {MAX_BASE_REVISION} (2^63-1)"),
            ));
        }
        Ok(Self(value))
    }
}

impl fmt::Display for BaseRevision {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl Serialize for BaseRevision {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for BaseRevision {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = u64::deserialize(deserializer)?;
        Self::try_new(value).map_err(de::Error::custom)
    }
}

/// A workspace revision: monotonically increasing, starting at 1, no gaps (§4.2).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Revision(u64);

impl Revision {
    pub fn get(self) -> u64 {
        self.0
    }

    pub fn try_new(value: u64) -> Result<Self, InvalidValue> {
        if value == 0 {
            return Err(InvalidValue::new(
                "Revision",
                "0",
                "revisions start at 1",
            ));
        }
        Ok(Self(value))
    }
}

impl fmt::Display for Revision {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

impl Serialize for Revision {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for Revision {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = u64::deserialize(deserializer)?;
        Self::try_new(value).map_err(de::Error::custom)
    }
}

// ---------------------------------------------------------------------------
// Closed enums
// ---------------------------------------------------------------------------

/// The nine synchronizable entity types (§2). Any other value is `unknown_entity_type`;
/// adding one is a breaking change because clients reject what they do not know.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EntityType {
    LedgerCategory,
    LedgerTransaction,
    WebsiteCategory,
    Website,
    DataCollection,
    DataRecord,
    UserPreferences,
    DashboardLayout,
    AutomationDefinition,
}

impl EntityType {
    pub const ALL: [EntityType; ENTITY_TYPE_COUNT] = [
        EntityType::LedgerCategory,
        EntityType::LedgerTransaction,
        EntityType::WebsiteCategory,
        EntityType::Website,
        EntityType::DataCollection,
        EntityType::DataRecord,
        EntityType::UserPreferences,
        EntityType::DashboardLayout,
        EntityType::AutomationDefinition,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            EntityType::LedgerCategory => "ledger.category",
            EntityType::LedgerTransaction => "ledger.transaction",
            EntityType::WebsiteCategory => "website.category",
            EntityType::Website => "website",
            EntityType::DataCollection => "data.collection",
            EntityType::DataRecord => "data.record",
            EntityType::UserPreferences => "user.preferences",
            EntityType::DashboardLayout => "dashboard.layout",
            EntityType::AutomationDefinition => "automation.definition",
        }
    }

    /// `$defs` entry in `schema/sync-v3.schema.json` (and `entityDataSchemas` in
    /// `cases.json`) that governs this entity's `data` payload.
    pub fn data_schema_name(self) -> &'static str {
        match self {
            EntityType::LedgerCategory => "LedgerCategoryData",
            EntityType::LedgerTransaction => "LedgerTransactionData",
            EntityType::WebsiteCategory => "WebsiteCategoryData",
            EntityType::Website => "WebsiteData",
            EntityType::DataCollection => "CollectionData",
            EntityType::DataRecord => "RecordData",
            EntityType::UserPreferences
            | EntityType::DashboardLayout
            | EntityType::AutomationDefinition => "PersonalStateData",
        }
    }

    /// Singleton personal-state entities: `delete` is `delete_unsupported`.
    pub fn is_personal_state(self) -> bool {
        matches!(
            self,
            EntityType::UserPreferences
                | EntityType::DashboardLayout
                | EntityType::AutomationDefinition
        )
    }
}

impl fmt::Display for EntityType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for EntityType {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        EntityType::ALL
            .into_iter()
            .find(|candidate| candidate.as_str() == value)
            .ok_or_else(|| {
                InvalidValue::new(
                    "EntityType",
                    value,
                    "not one of the 9 closed entity types",
                )
            })
    }
}

impl Serialize for EntityType {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for EntityType {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<EntityType>()
            .map_err(|error: InvalidValue| de::Error::custom(error))
    }
}

/// `operation`: `upsert` carries a full snapshot, `delete` carries nothing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Operation {
    Upsert,
    Delete,
}

impl Operation {
    pub const ALL: [Operation; 2] = [Operation::Upsert, Operation::Delete];

    pub fn as_str(self) -> &'static str {
        match self {
            Operation::Upsert => "upsert",
            Operation::Delete => "delete",
        }
    }
}

impl fmt::Display for Operation {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for Operation {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        match value {
            "upsert" => Ok(Operation::Upsert),
            "delete" => Ok(Operation::Delete),
            other => Err(InvalidValue::new(
                "Operation",
                other,
                "must be `upsert` or `delete`",
            )),
        }
    }
}

impl Serialize for Operation {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for Operation {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<Operation>()
            .map_err(|error: InvalidValue| de::Error::custom(error))
    }
}

/// The thirteen rejection reasons (§3.3), a closed set.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RejectionReason {
    InvalidId,
    InvalidFields,
    InvalidOperation,
    InvalidBaseRevision,
    InvalidData,
    UnknownEntityType,
    EntityIdUnavailable,
    CategoryNotFound,
    CategoryTypeMismatch,
    CategoryHasTransactions,
    CollectionNotFound,
    CollectionIdImmutable,
    DeleteUnsupported,
}

impl RejectionReason {
    pub const ALL: [RejectionReason; REJECTION_REASON_COUNT] = [
        RejectionReason::InvalidId,
        RejectionReason::InvalidFields,
        RejectionReason::InvalidOperation,
        RejectionReason::InvalidBaseRevision,
        RejectionReason::InvalidData,
        RejectionReason::UnknownEntityType,
        RejectionReason::EntityIdUnavailable,
        RejectionReason::CategoryNotFound,
        RejectionReason::CategoryTypeMismatch,
        RejectionReason::CategoryHasTransactions,
        RejectionReason::CollectionNotFound,
        RejectionReason::CollectionIdImmutable,
        RejectionReason::DeleteUnsupported,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            RejectionReason::InvalidId => "invalid_id",
            RejectionReason::InvalidFields => "invalid_fields",
            RejectionReason::InvalidOperation => "invalid_operation",
            RejectionReason::InvalidBaseRevision => "invalid_base_revision",
            RejectionReason::InvalidData => "invalid_data",
            RejectionReason::UnknownEntityType => "unknown_entity_type",
            RejectionReason::EntityIdUnavailable => "entity_id_unavailable",
            RejectionReason::CategoryNotFound => "category_not_found",
            RejectionReason::CategoryTypeMismatch => "category_type_mismatch",
            RejectionReason::CategoryHasTransactions => "category_has_transactions",
            RejectionReason::CollectionNotFound => "collection_not_found",
            RejectionReason::CollectionIdImmutable => "collection_id_immutable",
            RejectionReason::DeleteUnsupported => "delete_unsupported",
        }
    }
}

impl fmt::Display for RejectionReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for RejectionReason {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        RejectionReason::ALL
            .into_iter()
            .find(|candidate| candidate.as_str() == value)
            .ok_or_else(|| {
                InvalidValue::new(
                    "RejectionReason",
                    value,
                    "not one of the 13 closed rejection reasons",
                )
            })
    }
}

impl Serialize for RejectionReason {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for RejectionReason {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<RejectionReason>()
            .map_err(|error: InvalidValue| de::Error::custom(error))
    }
}

/// `strategy` on `POST /sync/conflicts/{id}/resolve` (§5.2).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ConflictStrategy {
    Local,
    Remote,
}

impl ConflictStrategy {
    pub fn as_str(self) -> &'static str {
        match self {
            ConflictStrategy::Local => "local",
            ConflictStrategy::Remote => "remote",
        }
    }
}

impl fmt::Display for ConflictStrategy {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for ConflictStrategy {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        match value {
            "local" => Ok(ConflictStrategy::Local),
            "remote" => Ok(ConflictStrategy::Remote),
            other => Err(InvalidValue::new(
                "ConflictStrategy",
                other,
                "must be `local` or `remote`",
            )),
        }
    }
}

impl Serialize for ConflictStrategy {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for ConflictStrategy {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<ConflictStrategy>()
            .map_err(|error: InvalidValue| de::Error::custom(error))
    }
}

/// Client platform accepted by `POST /clients/enroll`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Platform {
    Windows,
    Macos,
    Android,
    Linux,
}

impl Platform {
    pub const ALL: [Platform; 4] = [
        Platform::Windows,
        Platform::Macos,
        Platform::Android,
        Platform::Linux,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Platform::Windows => "windows",
            Platform::Macos => "macos",
            Platform::Android => "android",
            Platform::Linux => "linux",
        }
    }
}

impl fmt::Display for Platform {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for Platform {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        Platform::ALL
            .into_iter()
            .find(|candidate| candidate.as_str() == value)
            .ok_or_else(|| {
                InvalidValue::new("Platform", value, "must be windows/macos/android/linux")
            })
    }
}

impl Serialize for Platform {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for Platform {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<Platform>()
            .map_err(|error: InvalidValue| de::Error::custom(error))
    }
}

/// Ledger direction, shared by `ledger.category` and `ledger.transaction`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum LedgerDirection {
    Income,
    Expense,
}

impl LedgerDirection {
    pub fn as_str(self) -> &'static str {
        match self {
            LedgerDirection::Income => "income",
            LedgerDirection::Expense => "expense",
        }
    }
}

impl fmt::Display for LedgerDirection {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for LedgerDirection {
    type Err = InvalidValue;

    fn from_str(value: &str) -> Result<Self, InvalidValue> {
        match value {
            "income" => Ok(LedgerDirection::Income),
            "expense" => Ok(LedgerDirection::Expense),
            other => Err(InvalidValue::new(
                "LedgerDirection",
                other,
                "must be `income` or `expense`",
            )),
        }
    }
}

impl Serialize for LedgerDirection {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for LedgerDirection {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let value = String::deserialize(deserializer)?;
        value
            .parse::<LedgerDirection>()
            .map_err(|error: InvalidValue| de::Error::custom(error))
    }
}

// ---------------------------------------------------------------------------
// Entity payloads (the `data` object, SR-2)
// ---------------------------------------------------------------------------

/// `ledger.category` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LedgerCategoryData {
    pub name: BoundedStr<1, 80>,
    #[serde(rename = "type")]
    pub direction: LedgerDirection,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub icon: Option<BoundedStr<0, 30>>,
}

/// `ledger.transaction` payload. `amount` is a decimal string, never a JSON number.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LedgerTransactionData {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub category_id: Option<Uuid>,
    #[serde(rename = "type")]
    pub direction: LedgerDirection,
    pub amount: DecimalString,
    pub description: BoundedStr<1, 200>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub merchant: Option<BoundedStr<0, 120>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<BoundedStr<0, 500>>,
    pub occurred_at: IsoUtc,
}

/// `website.category` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebsiteCategoryData {
    pub name: BoundedStr<1, 80>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub order: Option<u64>,
}

/// `website` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WebsiteData {
    pub name: BoundedStr<1, 120>,
    pub url: HttpUrl,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub icon: Option<BoundedStr<0, 500>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<BoundedStr<0, 500>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub category_id: Option<Uuid>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub favorite: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub order: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_visited_at: Option<IsoUtc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub created_at: Option<IsoUtc>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated_at: Option<IsoUtc>,
}

/// `data.collection` payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CollectionData {
    pub name: BoundedStr<1, 120>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<BoundedStr<0, 500>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub icon: Option<BoundedStr<0, 30>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tone: Option<BoundedStr<0, 30>>,
}

/// `data.record` payload. `collectionId` is immutable after creation
/// (`collection_id_immutable`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecordData {
    pub collection_id: Uuid,
    pub name: BoundedStr<1, 160>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub status: Option<BoundedStr<0, 40>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub category: Option<BoundedStr<0, 80>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub data_json: Option<Map<String, Value>>,
}

/// `user.preferences` / `dashboard.layout` / `automation.definition` payload.
///
/// Every field is optional; the schema deliberately does not set
/// `additionalProperties: false` for this shape, but this type does reject unknown
/// keys so that clients cannot silently depend on keys Core drops.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PersonalStateData {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<BoundedStr<0, 120>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<BoundedStr<0, 500>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub enabled: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trigger_type: Option<BoundedStr<0, 30>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub trigger_config_json: Option<Map<String, Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub workflow_json: Option<Vec<Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub theme: Option<BoundedStr<0, 30>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub language: Option<BoundedStr<0, 30>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timezone: Option<BoundedStr<0, 80>>,
}

/// A validated entity payload, tagged by the entity type it was parsed as.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "entityType")]
pub enum EntityPayload {
    #[serde(rename = "ledger.category")]
    LedgerCategory(LedgerCategoryData),
    #[serde(rename = "ledger.transaction")]
    LedgerTransaction(LedgerTransactionData),
    #[serde(rename = "website.category")]
    WebsiteCategory(WebsiteCategoryData),
    #[serde(rename = "website")]
    Website(WebsiteData),
    #[serde(rename = "data.collection")]
    Collection(CollectionData),
    #[serde(rename = "data.record")]
    Record(RecordData),
    #[serde(rename = "user.preferences")]
    UserPreferences(PersonalStateData),
    #[serde(rename = "dashboard.layout")]
    DashboardLayout(PersonalStateData),
    #[serde(rename = "automation.definition")]
    AutomationDefinition(PersonalStateData),
}

impl EntityPayload {
    pub fn entity_type(&self) -> EntityType {
        match self {
            EntityPayload::LedgerCategory(_) => EntityType::LedgerCategory,
            EntityPayload::LedgerTransaction(_) => EntityType::LedgerTransaction,
            EntityPayload::WebsiteCategory(_) => EntityType::WebsiteCategory,
            EntityPayload::Website(_) => EntityType::Website,
            EntityPayload::Collection(_) => EntityType::DataCollection,
            EntityPayload::Record(_) => EntityType::DataRecord,
            EntityPayload::UserPreferences(_) => EntityType::UserPreferences,
            EntityPayload::DashboardLayout(_) => EntityType::DashboardLayout,
            EntityPayload::AutomationDefinition(_) => EntityType::AutomationDefinition,
        }
    }
}

/// Validate a `data` object against the payload schema selected by `entityType`
/// (SR-2). This is the only place entity payloads are interpreted: the transport
/// layer keeps `data` opaque, exactly like the JSON Schema does (`"type": "object"`).
pub fn parse_entity_data(
    entity_type: EntityType,
    data: &Value,
) -> Result<EntityPayload, EntityDataError> {
    fn convert<T: DeserializeOwned>(
        entity_type: EntityType,
        data: &Value,
    ) -> Result<T, EntityDataError> {
        serde_json::from_value(data.clone()).map_err(|error| EntityDataError {
            entity_type,
            message: error.to_string(),
        })
    }

    Ok(match entity_type {
        EntityType::LedgerCategory => {
            EntityPayload::LedgerCategory(convert(entity_type, data)?)
        }
        EntityType::LedgerTransaction => {
            EntityPayload::LedgerTransaction(convert(entity_type, data)?)
        }
        EntityType::WebsiteCategory => {
            EntityPayload::WebsiteCategory(convert(entity_type, data)?)
        }
        EntityType::Website => EntityPayload::Website(convert(entity_type, data)?),
        EntityType::DataCollection => EntityPayload::Collection(convert(entity_type, data)?),
        EntityType::DataRecord => EntityPayload::Record(convert(entity_type, data)?),
        EntityType::UserPreferences => {
            EntityPayload::UserPreferences(convert(entity_type, data)?)
        }
        EntityType::DashboardLayout => {
            EntityPayload::DashboardLayout(convert(entity_type, data)?)
        }
        EntityType::AutomationDefinition => {
            EntityPayload::AutomationDefinition(convert(entity_type, data)?)
        }
    })
}

// ---------------------------------------------------------------------------
// Shared wire helpers
// ---------------------------------------------------------------------------

/// A JSON object, or `null` — with the key *present*.
///
/// The schema marks `data`/`current`/`local`/`remote` required and allows `null`, so a
/// missing key must never be conflated with `null`. Using this type (instead of
/// `Option<Map<..>>`) makes serde reject a payload that omits the key entirely.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct NullableObject(Option<Map<String, Value>>);

impl NullableObject {
    /// Wrap a snapshot.
    pub fn some(object: Map<String, Value>) -> Self {
        Self(Some(object))
    }

    /// The explicit `null` tombstone / "no remote snapshot" case.
    pub fn null() -> Self {
        Self(None)
    }

    pub fn is_null(&self) -> bool {
        self.0.is_none()
    }

    pub fn as_object(&self) -> Option<&Map<String, Value>> {
        self.0.as_ref()
    }

    pub fn into_option(self) -> Option<Map<String, Value>> {
        self.0
    }
}

impl Serialize for NullableObject {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match &self.0 {
            Some(object) => object.serialize(serializer),
            None => serializer.serialize_none(),
        }
    }
}

impl<'de> Deserialize<'de> for NullableObject {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        // Deliberately goes through `Value` (i.e. `deserialize_any`): serde's
        // "missing field" deserializer answers `deserialize_option` with `None`, so
        // deserializing `Option<Map<..>>` directly would turn an *absent* required key
        // into `null`. `Value::deserialize` surfaces `missing field` instead.
        match Value::deserialize(deserializer)? {
            Value::Null => Ok(NullableObject(None)),
            Value::Object(object) => Ok(NullableObject(Some(object))),
            other => Err(de::Error::custom(format!(
                "expected a JSON object or null, got {}",
                json_type_name(&other)
            ))),
        }
    }
}

fn json_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "a boolean",
        Value::Number(_) => "a number",
        Value::String(_) => "a string",
        Value::Array(_) => "an array",
        Value::Object(_) => "an object",
    }
}

fn deserialize_bounded_vec<'de, D, T>(
    deserializer: D,
    min: usize,
    max: usize,
    field: &'static str,
) -> Result<Vec<T>, D::Error>
where
    D: Deserializer<'de>,
    T: Deserialize<'de>,
{
    let items = Vec::<T>::deserialize(deserializer)?;
    if items.len() < min || items.len() > max {
        return Err(de::Error::custom(format!(
            "`{field}` must contain {min}..={max} items, got {}",
            items.len()
        )));
    }
    Ok(items)
}

fn de_mutations<'de, D>(deserializer: D) -> Result<Vec<Mutation>, D::Error>
where
    D: Deserializer<'de>,
{
    deserialize_bounded_vec(deserializer, 1, 100, "mutations")
}

fn de_results<'de, D>(deserializer: D) -> Result<Vec<MutationResult>, D::Error>
where
    D: Deserializer<'de>,
{
    deserialize_bounded_vec(deserializer, 0, 100, "results")
}

fn de_changes<'de, D>(deserializer: D) -> Result<Vec<Change>, D::Error>
where
    D: Deserializer<'de>,
{
    deserialize_bounded_vec(deserializer, 0, 100, "changes")
}

fn de_snapshot_entities<'de, D>(deserializer: D) -> Result<Vec<SnapshotEntity>, D::Error>
where
    D: Deserializer<'de>,
{
    // §11.1 caps `limit` at 500, so a page can never exceed that many rows.
    deserialize_bounded_vec(deserializer, 0, 500, "entities")
}

/// Remove a required key from a buffered object, converting it to `T`.
fn take_field<T: DeserializeOwned>(
    fields: &mut Map<String, Value>,
    key: &'static str,
) -> Result<T, String> {
    let value = fields
        .remove(key)
        .ok_or_else(|| format!("missing field `{key}`"))?;
    serde_json::from_value(value).map_err(|error| format!("invalid field `{key}`: {error}"))
}

fn reject_unknown(
    fields: &Map<String, Value>,
    context: &str,
    allowed: &[&str],
) -> Result<(), String> {
    if fields.is_empty() {
        return Ok(());
    }
    let mut unknown: Vec<&str> = fields.keys().map(String::as_str).collect();
    unknown.sort_unstable();
    Err(format!(
        "unknown field(s) {unknown:?} in {context}; allowed: {allowed:?}"
    ))
}

// ---------------------------------------------------------------------------
// POST /api/v1/sync/mutations — request
// ---------------------------------------------------------------------------

/// One mutation. `mutationId` is the client-generated idempotency key and must never
/// be reused for a different change (§3.4).
///
/// `Deserialize` is written by hand (SR-3): it delegates to `MutationWire`, which is
/// `deny_unknown_fields`, and then rejects `operation = delete` carrying `data`.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Mutation {
    pub mutation_id: Uuid,
    pub entity_type: EntityType,
    pub entity_id: Uuid,
    pub operation: Operation,
    pub base_revision: BaseRevision,
    /// Opaque here on purpose: the JSON Schema constrains `Mutation.data` to
    /// `{"type": "object"}` only. Use [`parse_entity_data`] for SR-2 validation.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Map<String, Value>>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct MutationWire {
    mutation_id: Uuid,
    entity_type: EntityType,
    entity_id: Uuid,
    operation: Operation,
    base_revision: BaseRevision,
    #[serde(default)]
    data: Option<Map<String, Value>>,
}

impl<'de> Deserialize<'de> for Mutation {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let wire = MutationWire::deserialize(deserializer)?;
        if wire.operation == Operation::Delete && wire.data.is_some() {
            // SR-3: `delete` must omit `data`; carrying it is `invalid_data`.
            return Err(de::Error::custom(
                "SR-3: operation=delete must not carry `data`",
            ));
        }
        Ok(Mutation {
            mutation_id: wire.mutation_id,
            entity_type: wire.entity_type,
            entity_id: wire.entity_id,
            operation: wire.operation,
            base_revision: wire.base_revision,
            data: wire.data,
        })
    }
}

impl Mutation {
    /// SR-2: the payload of an `upsert`, validated against its entity schema.
    pub fn entity_payload(&self) -> Result<Option<EntityPayload>, EntityDataError> {
        match &self.data {
            Some(data) => parse_entity_data(self.entity_type, &Value::Object(data.clone())).map(Some),
            None => Ok(None),
        }
    }
}

/// The batch body of `POST /api/v1/sync/mutations`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MutationBatch {
    pub protocol_version: ProtocolVersion,
    /// 1..=100, processed in order, no reordering (`api/sync.py:42`).
    #[serde(deserialize_with = "de_mutations")]
    pub mutations: Vec<Mutation>,
}

impl MutationBatch {
    /// Batch-level invariants that serde already enforces; kept so callers can
    /// validate programmatically built batches before sending them.
    pub fn validate(&self) -> Result<(), ContractViolation> {
        if self.mutations.is_empty() || self.mutations.len() > 100 {
            return Err(ContractViolation::new(
                "contract §3.1",
                format!(
                    "mutations must contain 1..=100 items, got {}",
                    self.mutations.len()
                ),
            ));
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// POST /api/v1/sync/mutations — response
// ---------------------------------------------------------------------------

/// `applied`: the write landed, `revision` is the new workspace revision.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AppliedResult {
    pub mutation_id: Uuid,
    pub entity_type: EntityType,
    pub entity_id: Uuid,
    pub base_revision: BaseRevision,
    pub revision: Revision,
}

/// `conflict`: optimistic-concurrency failure, Core wrote nothing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConflictResult {
    pub mutation_id: Uuid,
    pub entity_type: EntityType,
    pub entity_id: Uuid,
    pub base_revision: BaseRevision,
    pub current_revision: u64,
    /// Core's current snapshot, or `null` when the row is deleted. Required key.
    pub current: NullableObject,
    pub deleted: bool,
}

/// `rejected`: the request itself was invalid, Core wrote nothing.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RejectedResult {
    pub mutation_id: Uuid,
    /// Free-form, not [`EntityType`]: `unknown_entity_type` echoes the offending value.
    pub entity_type: String,
    /// Free-form, not [`Uuid`]: an unparseable id is echoed verbatim.
    pub entity_id: String,
    /// `i64` rather than [`BaseRevision`]: `invalid_base_revision` echoes the offending value.
    pub base_revision: i64,
    pub reason: RejectionReason,
}

/// Early-return `rejected`: only produced when `mutationId` is not a UUID, so
/// `entityType`/`entityId`/`baseRevision` are absent (`service.py:83-85`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EarlyRejectedResult {
    /// `null` (nothing to echo) or the raw offending value, which is *not* a UUID.
    pub mutation_id: Option<String>,
    /// Pinned to `invalid_id` by the schema.
    pub reason: RejectionReason,
}

/// One entry of `MutationsResponse.results`, same order and length as the request.
///
/// `Deserialize` is written by hand because two variants share `status = "rejected"`;
/// they are told apart by their exact key set, which also makes every branch reject
/// fields belonging to another branch (stricter than `deny_unknown_fields` alone).
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum MutationResult {
    Applied(AppliedResult),
    Conflict(ConflictResult),
    #[serde(rename = "rejected")]
    Rejected(RejectedResult),
    /// Wire-identical `status` to [`MutationResult::Rejected`]; distinguished by the
    /// absence of `entityType`/`entityId`/`baseRevision`.
    #[serde(rename = "rejected")]
    RejectedEarly(EarlyRejectedResult),
}

impl MutationResult {
    pub fn status(&self) -> &'static str {
        match self {
            MutationResult::Applied(_) => "applied",
            MutationResult::Conflict(_) => "conflict",
            MutationResult::Rejected(_) | MutationResult::RejectedEarly(_) => "rejected",
        }
    }

    pub fn mutation_id(&self) -> Option<&str> {
        match self {
            MutationResult::Applied(result) => Some(result.mutation_id.as_str()),
            MutationResult::Conflict(result) => Some(result.mutation_id.as_str()),
            MutationResult::Rejected(result) => Some(result.mutation_id.as_str()),
            MutationResult::RejectedEarly(result) => result.mutation_id.as_deref(),
        }
    }
}

impl<'de> Deserialize<'de> for MutationResult {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let mut fields = Map::<String, Value>::deserialize(deserializer)?;
        let status: String = take_field(&mut fields, "status").map_err(de::Error::custom)?;

        match status.as_str() {
            "applied" => {
                let result = AppliedResult {
                    mutation_id: take_field(&mut fields, "mutationId").map_err(de::Error::custom)?,
                    entity_type: take_field(&mut fields, "entityType").map_err(de::Error::custom)?,
                    entity_id: take_field(&mut fields, "entityId").map_err(de::Error::custom)?,
                    base_revision: take_field(&mut fields, "baseRevision")
                        .map_err(de::Error::custom)?,
                    revision: take_field(&mut fields, "revision").map_err(de::Error::custom)?,
                };
                reject_unknown(
                    &fields,
                    "status=applied",
                    &["mutationId", "entityType", "entityId", "baseRevision", "revision"],
                )
                .map_err(de::Error::custom)?;
                Ok(MutationResult::Applied(result))
            }
            "conflict" => {
                let result = ConflictResult {
                    mutation_id: take_field(&mut fields, "mutationId").map_err(de::Error::custom)?,
                    entity_type: take_field(&mut fields, "entityType").map_err(de::Error::custom)?,
                    entity_id: take_field(&mut fields, "entityId").map_err(de::Error::custom)?,
                    base_revision: take_field(&mut fields, "baseRevision")
                        .map_err(de::Error::custom)?,
                    current_revision: take_field(&mut fields, "currentRevision")
                        .map_err(de::Error::custom)?,
                    current: take_field(&mut fields, "current").map_err(de::Error::custom)?,
                    deleted: take_field(&mut fields, "deleted").map_err(de::Error::custom)?,
                };
                reject_unknown(
                    &fields,
                    "status=conflict",
                    &[
                        "mutationId",
                        "entityType",
                        "entityId",
                        "baseRevision",
                        "currentRevision",
                        "current",
                        "deleted",
                    ],
                )
                .map_err(de::Error::custom)?;
                Ok(MutationResult::Conflict(result))
            }
            "rejected" => {
                // The early shape is exactly {mutationId, status, reason}; anything
                // else means the server had already parsed entityType/entityId.
                let early = fields
                    .keys()
                    .all(|key| key == "mutationId" || key == "reason");
                if early {
                    let result = EarlyRejectedResult {
                        mutation_id: take_field(&mut fields, "mutationId")
                            .map_err(de::Error::custom)?,
                        reason: take_field(&mut fields, "reason").map_err(de::Error::custom)?,
                    };
                    if result.reason != RejectionReason::InvalidId {
                        return Err(de::Error::custom(format!(
                            "early-rejected shape requires reason=invalid_id, got `{}`",
                            result.reason
                        )));
                    }
                    reject_unknown(
                        &fields,
                        "status=rejected (early)",
                        &["mutationId", "status", "reason"],
                    )
                    .map_err(de::Error::custom)?;
                    Ok(MutationResult::RejectedEarly(result))
                } else {
                    let result = RejectedResult {
                        mutation_id: take_field(&mut fields, "mutationId")
                            .map_err(de::Error::custom)?,
                        entity_type: take_field(&mut fields, "entityType")
                            .map_err(de::Error::custom)?,
                        entity_id: take_field(&mut fields, "entityId")
                            .map_err(de::Error::custom)?,
                        base_revision: take_field(&mut fields, "baseRevision")
                            .map_err(de::Error::custom)?,
                        reason: take_field(&mut fields, "reason").map_err(de::Error::custom)?,
                    };
                    reject_unknown(
                        &fields,
                        "status=rejected",
                        &[
                            "mutationId",
                            "entityType",
                            "entityId",
                            "baseRevision",
                            "reason",
                        ],
                    )
                    .map_err(de::Error::custom)?;
                    Ok(MutationResult::Rejected(result))
                }
            }
            other => Err(de::Error::custom(format!(
                "unknown status `{other}`; expected applied/conflict/rejected"
            ))),
        }
    }
}

/// `POST /api/v1/sync/mutations` response. Always `200` unless auth or protocol
/// version failed; `results` is the same length and order as the request.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MutationsResponse {
    pub protocol_version: ProtocolVersion,
    #[serde(deserialize_with = "de_results")]
    pub results: Vec<MutationResult>,
}

impl MutationsResponse {
    pub fn validate(&self) -> Result<(), ContractViolation> {
        if self.results.len() > 100 {
            return Err(ContractViolation::new(
                "contract §3.2",
                format!(
                    "results must contain at most 100 items, got {}",
                    self.results.len()
                ),
            ));
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// GET /api/v1/sync/changes
// ---------------------------------------------------------------------------

/// One change in a page. `upsert` carries a full snapshot, `delete` carries `null`
/// (SR-8 is enforced at deserialization time).
///
/// `Deserialize` is written by hand: it delegates to `ChangeWire`
/// (`deny_unknown_fields`) and then enforces the `operation` ↔ `data` pairing.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Change {
    pub revision: Revision,
    pub entity_type: EntityType,
    pub entity_id: Uuid,
    pub operation: Operation,
    /// `Some` for `upsert` (full snapshot), `None` for `delete`. Serialized as `null`
    /// for deletes, which is what the contract mandates.
    pub data: Option<Map<String, Value>>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ChangeWire {
    revision: Revision,
    entity_type: EntityType,
    entity_id: Uuid,
    operation: Operation,
    data: NullableObject,
}

impl<'de> Deserialize<'de> for Change {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let wire = ChangeWire::deserialize(deserializer)?;
        let change = Change {
            revision: wire.revision,
            entity_type: wire.entity_type,
            entity_id: wire.entity_id,
            operation: wire.operation,
            data: wire.data.0,
        };
        match (change.operation, change.data.is_some()) {
            (Operation::Upsert, false) => Err(de::Error::custom(
                "SR-8: operation=upsert must carry an object `data` snapshot",
            )),
            (Operation::Delete, true) => Err(de::Error::custom(
                "SR-8: operation=delete must carry `data: null`",
            )),
            _ => Ok(change),
        }
    }
}

impl Change {
    /// SR-2: the payload of an `upsert` change.
    pub fn entity_payload(&self) -> Result<Option<EntityPayload>, EntityDataError> {
        match &self.data {
            Some(data) => {
                parse_entity_data(self.entity_type, &Value::Object(data.clone())).map(Some)
            }
            None => Ok(None),
        }
    }
}

/// One page of `GET /api/v1/sync/changes`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ChangesResponse {
    pub protocol_version: ProtocolVersion,
    #[serde(deserialize_with = "de_changes")]
    pub changes: Vec<Change>,
    /// Next cursor the client must send; echoes the request value on an empty page.
    pub cursor: u64,
    pub has_more: bool,
    /// Current maximum revision of the workspace, for the "caught up" check.
    pub workspace_revision: u64,
}

impl ChangesResponse {
    /// SR-5 (cursor within the workspace), SR-6 (cursor == last revision) and
    /// SR-7 (strictly increasing revisions).
    pub fn validate(&self) -> Result<(), ContractViolation> {
        if self.cursor > self.workspace_revision {
            return Err(ContractViolation::new(
                "SR-5",
                format!(
                    "cursor {} exceeds workspaceRevision {}",
                    self.cursor, self.workspace_revision
                ),
            ));
        }
        let mut previous: Option<u64> = None;
        for change in &self.changes {
            let revision = change.revision.get();
            if let Some(previous) = previous {
                if revision <= previous {
                    return Err(ContractViolation::new(
                        "SR-7",
                        format!("revision {revision} does not follow {previous}"),
                    ));
                }
            }
            previous = Some(revision);
        }
        if let Some(last) = self.changes.last() {
            let last_revision = last.revision.get();
            if self.cursor != last_revision {
                return Err(ContractViolation::new(
                    "SR-6",
                    format!(
                        "cursor {} must equal the last revision {last_revision}",
                        self.cursor
                    ),
                ));
            }
        }
        Ok(())
    }

    /// `true` when the client has fetched everything (`hasMore == false` and the
    /// cursor reached the workspace revision).
    pub fn is_caught_up(&self) -> bool {
        !self.has_more && self.cursor == self.workspace_revision
    }
}

// ---------------------------------------------------------------------------
// GET /api/v1/sync/snapshot (§11)
// ---------------------------------------------------------------------------

/// One entity of a [`SnapshotPage`].
///
/// Tombstones are included on purpose: `deleted: true` + `data: null` is the only
/// way a client learns that a row is gone remotely. `syncRevision` is the
/// entity-level revision — the `baseRevision` of the next push — never a change-log
/// revision, so two rows may legitimately share it.
///
/// `Deserialize` is written by hand to enforce the tombstone pairing (a §11.2 rule
/// the JSON Schema cannot express), mirroring [`Change`].
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotEntity {
    pub entity_type: EntityType,
    pub entity_id: Uuid,
    /// `0 ..= 2^63-1`. Reuses [`BaseRevision`] because that is exactly its range
    /// *and* its meaning: the value the next push must send as `baseRevision`.
    pub sync_revision: BaseRevision,
    pub deleted: bool,
    /// `Some` for a live row, `None` for a tombstone; serialized as `null` for
    /// tombstones, which is what §11.2 mandates.
    pub data: Option<Map<String, Value>>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SnapshotEntityWire {
    entity_type: EntityType,
    entity_id: Uuid,
    sync_revision: BaseRevision,
    deleted: bool,
    data: NullableObject,
}

impl<'de> Deserialize<'de> for SnapshotEntity {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let wire = SnapshotEntityWire::deserialize(deserializer)?;
        let entity = SnapshotEntity {
            entity_type: wire.entity_type,
            entity_id: wire.entity_id,
            sync_revision: wire.sync_revision,
            deleted: wire.deleted,
            data: wire.data.0,
        };
        match (entity.deleted, entity.data.is_some()) {
            (true, true) => Err(de::Error::custom(
                "§11.2: a tombstone (deleted=true) must carry `data: null`",
            )),
            (false, false) => Err(de::Error::custom(
                "§11.2: a live entity (deleted=false) must carry an object `data`",
            )),
            _ => Ok(entity),
        }
    }
}

impl SnapshotEntity {
    /// SR-2: the payload of a live entity. `None` for a tombstone.
    pub fn entity_payload(&self) -> Result<Option<EntityPayload>, EntityDataError> {
        match &self.data {
            Some(data) => {
                parse_entity_data(self.entity_type, &Value::Object(data.clone())).map(Some)
            }
            None => Ok(None),
        }
    }
}

/// One page of `GET /api/v1/sync/snapshot` (§11.2).
///
/// `workspaceRevision` is pinned by `snapshotId` for the whole paging run, so it
/// never advances while the client pages; `cursor` is `null` exactly when
/// `hasMore` is `false`.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SnapshotPage {
    pub protocol_version: ProtocolVersion,
    /// Opaque, `1..=512` chars. Must be echoed verbatim to fetch the next page.
    pub snapshot_id: BoundedStr<1, 512>,
    /// The revision this logical snapshot pinned (§11.3).
    pub workspace_revision: u64,
    /// At most 500 rows: §11.1 caps `limit` at 500.
    pub entities: Vec<SnapshotEntity>,
    /// Required key, nullable value: `None` means "this was the last page".
    pub cursor: Option<BoundedStr<1, 512>>,
    pub has_more: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SnapshotPageWire {
    protocol_version: ProtocolVersion,
    snapshot_id: BoundedStr<1, 512>,
    workspace_revision: u64,
    #[serde(deserialize_with = "de_snapshot_entities")]
    entities: Vec<SnapshotEntity>,
    /// `Value`, not `Option<..>`: serde answers a missing `Option` field with
    /// `None`, which would conflate an absent key with the contract's explicit
    /// `null`. `Value` surfaces `missing field` instead.
    cursor: Value,
    has_more: bool,
}

impl<'de> Deserialize<'de> for SnapshotPage {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let wire = SnapshotPageWire::deserialize(deserializer)?;
        let cursor = match wire.cursor {
            Value::Null => None,
            Value::String(raw) => {
                Some(BoundedStr::<1, 512>::try_new(raw).map_err(de::Error::custom)?)
            }
            other => {
                return Err(de::Error::custom(format!(
                    "`cursor` must be a 1..=512 character string or null, got {}",
                    json_type_name(&other)
                )));
            }
        };
        Ok(SnapshotPage {
            protocol_version: wire.protocol_version,
            snapshot_id: wire.snapshot_id,
            workspace_revision: wire.workspace_revision,
            entities: wire.entities,
            cursor,
            has_more: wire.has_more,
        })
    }
}

impl SnapshotPage {
    /// §11.2 cross-field rules: `cursor` is `null` **iff** `hasMore` is `false`, and
    /// no entity may be newer than the revision the snapshot pinned.
    pub fn validate(&self) -> Result<(), ContractViolation> {
        if self.cursor.is_some() != self.has_more {
            return Err(ContractViolation::new(
                "§11.2",
                format!(
                    "`cursor` must be null exactly when `hasMore` is false \
                     (cursor present: {}, hasMore: {})",
                    self.cursor.is_some(),
                    self.has_more
                ),
            ));
        }
        for entity in &self.entities {
            if entity.sync_revision.get() > self.workspace_revision {
                return Err(ContractViolation::new(
                    "§11.2",
                    format!(
                        "`syncRevision` {} exceeds `workspaceRevision` {} for {} {}",
                        entity.sync_revision,
                        self.workspace_revision,
                        entity.entity_type,
                        entity.entity_id
                    ),
                ));
            }
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Conflicts (local backend, user JWT)
// ---------------------------------------------------------------------------

/// One row of `GET /api/v1/sync/conflicts`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConflictPresentation {
    /// Local conflict row id. Not a UUID: the local backend owns the format.
    pub id: NonEmptyStr,
    pub entity_type: EntityType,
    pub entity_id: Uuid,
    pub local: NullableObject,
    pub local_deleted: bool,
    pub remote: NullableObject,
    pub remote_revision: u64,
    pub remote_deleted: bool,
    pub created_at: IsoUtc,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detected_at: Option<IsoUtc>,
    pub updated_at: IsoUtc,
    pub has_pending_tail: bool,
}

/// `GET /api/v1/sync/conflicts` response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConflictsResponse {
    pub conflicts: Vec<ConflictPresentation>,
}

/// Body of `POST /api/v1/sync/conflicts/{id}/resolve`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConflictResolution {
    pub strategy: ConflictStrategy,
    /// Optional optimistic guard; a mismatch is `409 conflict_snapshot_changed`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expected_remote_revision: Option<BaseRevision>,
}

// ---------------------------------------------------------------------------
// Enrollment
// ---------------------------------------------------------------------------

/// Body of `POST /api/v1/clients/enroll` (Core mode, user JWT).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EnrollmentRequest {
    pub installation_id: BoundedStr<1, 100>,
    pub name: BoundedStr<1, 120>,
    pub platform: Platform,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub app_version: Option<BoundedStr<0, 40>>,
}

/// The client record echoed inside an enrollment response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EnrolledClient {
    pub id: Uuid,
    pub installation_id: String,
    pub workspace_id: Uuid,
    pub name: String,
    pub platform: String,
    pub app_version: String,
}

/// `201` response of `POST /api/v1/clients/enroll`. `credential` is shown exactly
/// once; the response is served with `Cache-Control: no-store`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EnrollmentResponse {
    pub client: EnrolledClient,
    pub credential: ClientCredential,
    pub token_last4: TokenLast4,
    pub token_created_at: IsoUtc,
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

/// The only error body shape on the sync channel: `{"detail": "..."}`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ErrorResponse {
    pub detail: NonEmptyStr,
}

/// The `400` body of `GET /sync/changes` (and of a bad snapshot cursor): the cursor
/// is outside the workspace's history, so the client must resync from a snapshot
/// instead of blocking on `invalid_response` (§4.3, §11.5).
///
/// `detail` and `resyncRequired` are `const`s in the schema, so `Deserialize`
/// rejects any other value at the envelope layer rather than leaving it to a
/// semantic pass.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CursorError {
    /// Pinned to [`details::INVALID_SYNC_CURSOR`].
    pub detail: String,
    /// Pinned to `true`; kept as a field so the body round-trips byte-for-byte.
    pub resync_required: bool,
    pub workspace_revision: u64,
}

impl<'de> Deserialize<'de> for CursorError {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let mut fields = Map::<String, Value>::deserialize(deserializer)?;
        let error = CursorError {
            detail: take_field(&mut fields, "detail").map_err(de::Error::custom)?,
            resync_required: take_field(&mut fields, "resyncRequired").map_err(de::Error::custom)?,
            workspace_revision: take_field(&mut fields, "workspaceRevision")
                .map_err(de::Error::custom)?,
        };
        if error.detail != details::INVALID_SYNC_CURSOR {
            return Err(de::Error::custom(format!(
                "`detail` must be `{}`, got `{}`",
                details::INVALID_SYNC_CURSOR,
                error.detail
            )));
        }
        if !error.resync_required {
            return Err(de::Error::custom("`resyncRequired` is pinned to true"));
        }
        reject_unknown(
            &fields,
            "CursorError",
            &["detail", "resyncRequired", "workspaceRevision"],
        )
        .map_err(de::Error::custom)?;
        Ok(error)
    }
}

/// Well-known `detail` values from the contract (§1, §4.3, §5.2, §6).
pub mod details {
    pub const SYNC_PROTOCOL_MISMATCH: &str = "sync_protocol_mismatch";
    pub const INVALID_SYNC_CURSOR: &str = "Invalid sync cursor";
    pub const CLIENT_ALREADY_ENROLLED: &str = "Client is already enrolled";
    pub const CLIENT_REVOKED: &str = "Client is revoked";
    pub const INVALID_RESOLUTION_STRATEGY: &str = "invalid_resolution_strategy";
    pub const SYNC_IN_PROGRESS: &str = "sync_in_progress";
    pub const CONFLICT_SNAPSHOT_CHANGED: &str = "conflict_snapshot_changed";
}
