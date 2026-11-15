//! Conformance tests for the frozen Sync Protocol v3 contract.
//!
//! Every assertion is driven by `packages/contracts/cases.json` — the same file the
//! Python and Node validators read (§10 of `sync-protocol-v3.md`). Fixture paths are
//! resolved from `CARGO_MANIFEST_DIR`, never from a hard-coded absolute path.
//!
//! Layer model, and why the tests are split this way:
//!
//! | layer | what it validates | owner |
//! | --- | --- | --- |
//! | transport | envelope shape, key whitelist, scalar formats, enum membership | serde types in `lib.rs` |
//! | invariants | SR-5/SR-6/SR-7 across fields | `ChangesResponse::validate` |
//! | payload | SR-2, the `data` object against its entity schema | `parse_entity_data` |
//!
//! `Mutation.data` / `Change.data` are opaque objects at the transport layer *because
//! the normative JSON Schema says `{"type": "object"}`* and validates nothing inside.
//! Entity payloads are therefore asserted through `parse_entity_data` — see
//! `valid_mutations_batch_keeps_entity_data_opaque` and
//! `semantic_naive_timestamp_is_rejected_by_the_payload_layer`.

use nexa_contracts::*;
use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/// `packages/contracts`, i.e. the directory holding `cases.json` and `samples/`.
fn contracts_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crate directory has a parent (packages/contracts)")
        .to_path_buf()
}

fn read_json(relative: &str) -> Value {
    let path = contracts_dir().join(relative);
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|error| panic!("cannot parse {} as JSON: {error}", path.display()))
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CasesFile {
    contract_version: u32,
    entity_types: Vec<String>,
    rejection_reasons: Vec<String>,
    entity_data_schemas: BTreeMap<String, String>,
    cases: Vec<Case>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Case {
    name: String,
    file: String,
    #[serde(default)]
    schema: Option<String>,
    /// Present for every entry; historical `semantic` rows omitted it and are still
    /// recognised through `rule`.
    #[serde(default)]
    kind: Option<String>,
    #[serde(default)]
    rule: Option<String>,
    #[serde(default)]
    expect: Option<Value>,
}

fn load_cases() -> CasesFile {
    let path = contracts_dir().join("cases.json");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|error| panic!("cannot parse {}: {error}", path.display()))
}

fn cases_of_kind<'a>(file: &'a CasesFile, kind: &str) -> Vec<&'a Case> {
    file.cases
        .iter()
        .filter(|case| match case.kind.as_deref() {
            Some(declared) => declared == kind,
            // Backwards compatibility: semantic rows used to omit `kind`.
            None => kind == "semantic" && case.rule.is_some(),
        })
        .collect()
}

/// Deserialize a fixture with the root type that `cases.json` assigns to it, then run
/// the response-level invariants. `Err` means "the contract rejected this document".
fn parse_as(schema: &str, value: Value) -> Result<(), String> {
    match schema {
        "MutationBatch" => {
            let batch: MutationBatch =
                serde_json::from_value(value).map_err(|error| error.to_string())?;
            batch.validate().map_err(|error| error.to_string())
        }
        "MutationsResponse" => {
            let response: MutationsResponse =
                serde_json::from_value(value).map_err(|error| error.to_string())?;
            response.validate().map_err(|error| error.to_string())
        }
        "ChangesResponse" => {
            let response: ChangesResponse =
                serde_json::from_value(value).map_err(|error| error.to_string())?;
            response.validate().map_err(|error| error.to_string())
        }
        "SnapshotPage" => {
            let page: SnapshotPage =
                serde_json::from_value(value).map_err(|error| error.to_string())?;
            page.validate().map_err(|error| error.to_string())
        }
        "CursorError" => serde_json::from_value::<CursorError>(value)
            .map(|_| ())
            .map_err(|error| error.to_string()),
        "ConflictsResponse" => serde_json::from_value::<ConflictsResponse>(value)
            .map(|_| ())
            .map_err(|error| error.to_string()),
        "ConflictResolution" => serde_json::from_value::<ConflictResolution>(value)
            .map(|_| ())
            .map_err(|error| error.to_string()),
        "EnrollmentRequest" => serde_json::from_value::<EnrollmentRequest>(value)
            .map(|_| ())
            .map_err(|error| error.to_string()),
        "EnrollmentResponse" => serde_json::from_value::<EnrollmentResponse>(value)
            .map(|_| ())
            .map_err(|error| error.to_string()),
        "ErrorResponse" => serde_json::from_value::<ErrorResponse>(value)
            .map(|_| ())
            .map_err(|error| error.to_string()),
        other => panic!("`{other}` is not a root schema this crate models; cases.json drifted"),
    }
}

fn parse_schema_only(schema: &str, value: Value) -> Result<Value, String> {
    // Round-tripping needs the typed value, so this helper returns the re-serialized
    // document instead of `()`; it also proves `Serialize` agrees with `Deserialize`.
    match schema {
        "MutationBatch" => serde_json::from_value::<MutationBatch>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize MutationBatch"))
            .map_err(|error| error.to_string()),
        "MutationsResponse" => serde_json::from_value::<MutationsResponse>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize MutationsResponse"))
            .map_err(|error| error.to_string()),
        "ChangesResponse" => serde_json::from_value::<ChangesResponse>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize ChangesResponse"))
            .map_err(|error| error.to_string()),
        "SnapshotPage" => serde_json::from_value::<SnapshotPage>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize SnapshotPage"))
            .map_err(|error| error.to_string()),
        "CursorError" => serde_json::from_value::<CursorError>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize CursorError"))
            .map_err(|error| error.to_string()),
        "ConflictsResponse" => serde_json::from_value::<ConflictsResponse>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize ConflictsResponse"))
            .map_err(|error| error.to_string()),
        "ConflictResolution" => serde_json::from_value::<ConflictResolution>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize ConflictResolution"))
            .map_err(|error| error.to_string()),
        "EnrollmentRequest" => serde_json::from_value::<EnrollmentRequest>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize EnrollmentRequest"))
            .map_err(|error| error.to_string()),
        "EnrollmentResponse" => serde_json::from_value::<EnrollmentResponse>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize EnrollmentResponse"))
            .map_err(|error| error.to_string()),
        "ErrorResponse" => serde_json::from_value::<ErrorResponse>(value)
            .map(|typed| serde_json::to_value(&typed).expect("serialize ErrorResponse"))
            .map_err(|error| error.to_string()),
        other => panic!("`{other}` is not a root schema this crate models; cases.json drifted"),
    }
}

fn require_schema(case: &Case) -> &str {
    case.schema
        .as_deref()
        .unwrap_or_else(|| panic!("case `{}` has no `schema`", case.name))
}

// ---------------------------------------------------------------------------
// cases.json ↔ Rust enums
// ---------------------------------------------------------------------------

#[test]
fn cases_json_matches_the_rust_closed_sets() {
    let file = load_cases();
    assert_eq!(
        file.contract_version as u8, SYNC_PROTOCOL_VERSION,
        "cases.json contractVersion disagrees with SYNC_PROTOCOL_VERSION"
    );

    let expected_entity_types: BTreeSet<&str> =
        file.entity_types.iter().map(String::as_str).collect();
    let actual_entity_types: BTreeSet<&str> =
        EntityType::ALL.iter().map(|value| value.as_str()).collect();
    assert_eq!(
        actual_entity_types, expected_entity_types,
        "EntityType must stay a 9-value closed set"
    );
    assert_eq!(EntityType::ALL.len(), ENTITY_TYPE_COUNT);

    let expected_reasons: BTreeSet<&str> =
        file.rejection_reasons.iter().map(String::as_str).collect();
    let actual_reasons: BTreeSet<&str> = RejectionReason::ALL
        .iter()
        .map(|value| value.as_str())
        .collect();
    assert_eq!(
        actual_reasons, expected_reasons,
        "RejectionReason must stay a 13-value closed set"
    );
    assert_eq!(RejectionReason::ALL.len(), REJECTION_REASON_COUNT);

    assert_eq!(
        file.entity_data_schemas.len(),
        ENTITY_TYPE_COUNT,
        "every entity type needs an entityDataSchemas entry"
    );
    for entity_type in EntityType::ALL {
        let expected = file
            .entity_data_schemas
            .get(entity_type.as_str())
            .unwrap_or_else(|| panic!("`{}` missing from entityDataSchemas", entity_type));
        assert_eq!(
            expected,
            entity_type.data_schema_name(),
            "payload schema name drifted for `{entity_type}`"
        );
    }
}

/// The three `kind` values `cases.json` is allowed to use.
const KINDS: [&str; 3] = ["valid", "schema-invalid", "semantic"];

#[test]
fn cases_json_is_internally_consistent() {
    let file = load_cases();

    // Kind counts are computed from `cases.json` instead of trusting a stale total:
    // a fixture can no longer be added without the count being recomputed, while the
    // pinned numbers below still make an accidental deletion as loud as an addition.
    let mut counts: BTreeMap<&str, usize> = KINDS.iter().map(|kind| (*kind, 0)).collect();
    for case in &file.cases {
        let kind = case
            .kind
            .as_deref()
            // Backwards compatibility: semantic rows used to omit `kind`.
            .or_else(|| case.rule.as_deref().map(|_| "semantic"))
            .unwrap_or_else(|| panic!("case `{}` declares neither `kind` nor `rule`", case.name));
        assert!(
            KINDS.contains(&kind),
            "case `{}` has unknown kind `{kind}`",
            case.name
        );
        *counts.get_mut(kind).expect("kind is one of KINDS") += 1;
    }

    assert_eq!(file.cases.len(), 35, "cases.json case count changed");
    assert_eq!(counts["valid"], 13, "kind=valid count changed");
    assert_eq!(
        counts["schema-invalid"], 13,
        "kind=schema-invalid count changed"
    );
    assert_eq!(counts["semantic"], 9, "kind=semantic count changed");
    assert_eq!(
        counts.values().sum::<usize>(),
        file.cases.len(),
        "every case must fall into exactly one kind"
    );

    let mut names = BTreeSet::new();
    for case in &file.cases {
        assert!(names.insert(case.name.as_str()), "duplicate case `{}`", case.name);
        assert!(
            contracts_dir().join(&case.file).is_file(),
            "case `{}` points at a missing file `{}`",
            case.name,
            case.file
        );
    }
    for case in cases_of_kind(&file, "semantic") {
        assert!(
            case.rule.is_some() && case.expect.is_some(),
            "semantic case `{}` must declare a rule and an expectation",
            case.name
        );
    }
}

// ---------------------------------------------------------------------------
// kind = valid
// ---------------------------------------------------------------------------

#[test]
fn valid_samples_deserialize() {
    let file = load_cases();
    let cases = cases_of_kind(&file, "valid");
    assert!(!cases.is_empty(), "cases.json has no valid samples");

    for case in cases {
        let value = read_json(&case.file);
        parse_as(require_schema(case), value)
            .unwrap_or_else(|error| panic!("valid case `{}` was rejected: {error}", case.name));
    }
}

#[test]
fn valid_samples_round_trip() {
    let file = load_cases();
    for case in cases_of_kind(&file, "valid") {
        let value = read_json(&case.file);
        let schema = require_schema(case).to_owned();
        let original = value.clone();
        let repeated = parse_schema_only(&schema, value)
            .unwrap_or_else(|error| panic!("valid case `{}` was rejected: {error}", case.name));
        assert_eq!(
            repeated, original,
            "case `{}` does not survive deserialize→serialize unchanged",
            case.name
        );
    }
}

#[test]
fn valid_mutations_batch_keeps_entity_data_opaque() {
    // The normative schema types `Mutation.data` as `{"type": "object"}` and delegates
    // payload checking to SR-2 (service level), so the transport layer stays opaque.
    // The fixture payload is contract-valid (`amount` is the decimal string "38.50",
    // `occurredAt` is ISO-8601 UTC), so the SR-2 layer must accept it.
    let batch: MutationBatch =
        serde_json::from_value(read_json("samples/valid/mutations-batch.json"))
            .expect("valid batch must deserialize");
    assert_eq!(batch.mutations.len(), 2);
    assert_eq!(batch.protocol_version.get(), SYNC_PROTOCOL_VERSION);
    assert_eq!(batch.mutations[0].entity_type, EntityType::LedgerTransaction);
    assert_eq!(batch.mutations[0].operation, Operation::Upsert);
    assert!(batch.mutations[0].data.is_some());
    assert_eq!(batch.mutations[1].operation, Operation::Delete);
    assert!(
        batch.mutations[1].data.is_none(),
        "delete mutations must omit `data`"
    );
    // SR-2 accepts this payload; a numeric amount is the negative control below.
    assert!(
        batch.mutations[0].entity_payload().is_ok(),
        "the valid fixture payload must pass entity validation"
    );
    let mut numeric_amount = read_json("samples/valid/mutations-batch.json");
    numeric_amount["mutations"][0]["data"]["amount"] = json!(38.5);
    let batch: MutationBatch =
        serde_json::from_value(numeric_amount).expect("envelope stays opaque");
    assert!(
        batch.mutations[0].entity_payload().is_err(),
        "amount as a JSON number must fail entity validation (SR-2)"
    );
}

// ---------------------------------------------------------------------------
// kind = schema-invalid
// ---------------------------------------------------------------------------

/// Service-level rules the JSON Schema cannot express: SR-2 is dispatched on
/// `entityType`, so a `MutationBatch` document only fails it once `data` is
/// interpreted. Used for negative cases that are "rejected by the contract" without
/// being rejected by the envelope (the same two-layer rule the Python validator uses).
fn rejected_by_service_rules(schema: &str, value: &Value) -> bool {
    match schema {
        "MutationBatch" => {
            let mutations = match value.get("mutations").and_then(Value::as_array) {
                Some(mutations) => mutations,
                None => return false,
            };
            mutations.iter().any(|mutation| {
                let data = match mutation.get("data") {
                    Some(data) => data,
                    None => return false, // `delete` never carries data (SR-3, transport layer)
                };
                let entity_type = mutation
                    .get("entityType")
                    .and_then(Value::as_str)
                    .and_then(|raw| raw.parse::<EntityType>().ok());
                match entity_type {
                    Some(entity_type) => parse_entity_data(entity_type, data).is_err(),
                    None => false, // unknown entity types are `unknown_entity_type`, not SR-2
                }
            })
        }
        _ => false,
    }
}

#[test]
fn schema_invalid_samples_are_rejected() {
    let file = load_cases();
    let cases = cases_of_kind(&file, "schema-invalid");
    assert!(!cases.is_empty(), "cases.json has no schema-invalid samples");

    let mut accepted_by_envelope = BTreeSet::new();
    let mut accepted_by_contract = BTreeSet::new();
    for case in &cases {
        let value = read_json(&case.file);
        let schema = require_schema(case);
        if parse_as(schema, value.clone()).is_ok() {
            accepted_by_envelope.insert(case.name.as_str());
            if !rejected_by_service_rules(schema, &value) {
                accepted_by_contract.insert(case.name.as_str());
            }
        }
    }

    assert!(
        accepted_by_envelope.is_empty(),
        "these schema-invalid cases passed the strict envelope: {accepted_by_envelope:?}"
    );
    assert!(
        accepted_by_contract.is_empty(),
        "these schema-invalid cases were accepted by every layer, so the contract does not \
         reject them at all: {accepted_by_contract:?}"
    );
}

// ---------------------------------------------------------------------------
// kind = semantic
// ---------------------------------------------------------------------------

#[test]
fn semantic_naive_timestamp_is_rejected_by_the_payload_layer() {
    // Same layer split as `semantic_amount_as_number_...`: the envelope cannot see inside
    // `data`, so SR-2 (entity payload validation) is what rejects a non-ISO timestamp.
    let batch: MutationBatch = serde_json::from_value(read_json(
        "samples/semantic/batch-naive-timestamp.json",
    ))
    .expect("envelope must stay schema-valid");
    assert_eq!(batch.mutations.len(), 1);
    assert!(
        batch.mutations[0].entity_payload().is_err(),
        "a naive (non-ISO-8601) occurredAt must fail entity validation (SR-2)"
    );
}

#[test]
fn semantic_amount_as_number_is_rejected_by_the_payload_layer() {
    let batch = read_json("samples/semantic/amount-as-number.json");
    // The envelope is schema-valid (the schema does not look inside `data`)…
    let batch: MutationBatch =
        serde_json::from_value(batch).expect("envelope must stay schema-valid");
    // …but SR-2 fails as soon as the payload is interpreted.
    let error = batch.mutations[0]
        .entity_payload()
        .expect_err("amount as a JSON number must be invalid_data");
    assert_eq!(error.entity_type, EntityType::LedgerTransaction);
    assert!(
        error.message.contains("expected a string"),
        "a numeric amount must be reported as a type error, got: {error}"
    );
    assert!(
        parse_entity_data(
            EntityType::LedgerTransaction,
            &json!({"type": "expense", "amount": "38.50", "description": "咖啡",
                    "occurredAt": "2026-11-15T02:30:00Z"})
        )
        .is_ok(),
        "the decimal-string form must be accepted"
    );
}

#[test]
fn semantic_delete_with_data_is_rejected() {
    let error = serde_json::from_value::<MutationBatch>(read_json(
        "samples/semantic/delete-with-data.json",
    ))
    .expect_err("delete carrying `data` must be rejected (SR-3)");
    assert!(
        error.to_string().contains("SR-3"),
        "unexpected error: {error}"
    );
}

#[test]
fn semantic_protocol_mismatch_is_rejected() {
    let document = read_json("samples/semantic/protocol-version-mismatch.json");
    // Assert on the version field itself: serde_json's object map is sorted, so the
    // whole-batch error may legitimately surface the `mutations` bound first.
    let version_error = serde_json::from_value::<ProtocolVersion>(document["protocolVersion"].clone())
        .expect_err("protocolVersion 2 must not deserialize (SR-1)");
    assert!(
        version_error.to_string().contains("only 3 is supported"),
        "unexpected error: {version_error}"
    );
    assert!(
        serde_json::from_value::<MutationBatch>(document).is_err(),
        "a protocol-2 batch must not deserialize at all"
    );
    // The 409 body the client must be able to read back:
    let body: ErrorResponse =
        serde_json::from_value(json!({"detail": "sync_protocol_mismatch"})).expect("error body");
    assert_eq!(body.detail.as_str(), details::SYNC_PROTOCOL_MISMATCH);
}

#[test]
fn semantic_invalid_fields_is_rejected() {
    let error = serde_json::from_value::<MutationBatch>(read_json(
        "samples/semantic/invalid-fields.json",
    ))
    .expect_err("a whitelist-outside field must be rejected (SR-4)");
    assert!(
        error.to_string().contains("unknown field"),
        "unexpected error: {error}"
    );
}

#[test]
fn semantic_cursor_beyond_workspace_revision_is_rejected() {
    let response: ChangesResponse =
        serde_json::from_value(read_json("samples/semantic/changes-cursor-beyond.json"))
            .expect("shape is valid, only the invariant is broken");
    let violation = response
        .validate()
        .expect_err("cursor > workspaceRevision must fail (SR-5)");
    assert_eq!(violation.rule, "SR-5");
}

#[test]
fn semantic_cursor_must_equal_the_last_revision() {
    let response: ChangesResponse =
        serde_json::from_value(read_json("samples/semantic/changes-cursor-not-last-revision.json"))
            .expect("shape is valid, only the invariant is broken");
    let violation = response
        .validate()
        .expect_err("cursor != last revision must fail (SR-6)");
    assert_eq!(violation.rule, "SR-6");
}

#[test]
fn semantic_revisions_must_be_strictly_increasing() {
    let response: ChangesResponse =
        serde_json::from_value(read_json("samples/semantic/changes-revision-order.json"))
            .expect("shape is valid, only the invariant is broken");
    let violation = response
        .validate()
        .expect_err("descending revisions must fail (SR-7)");
    assert_eq!(violation.rule, "SR-7");
}

#[test]
fn semantic_upsert_with_null_data_is_rejected() {
    let error = serde_json::from_value::<ChangesResponse>(read_json(
        "samples/semantic/changes-upsert-null-data.json",
    ))
    .expect_err("upsert with data=null must be rejected (SR-8)");
    assert!(
        error.to_string().contains("SR-8"),
        "unexpected error: {error}"
    );
}

// ---------------------------------------------------------------------------
// Shape coverage the fixtures only touch once
// ---------------------------------------------------------------------------

#[test]
fn mutation_result_branches_are_distinguished() {
    let uuid = "3f9d0d5e-1c4a-4f6e-9a1b-2c3d4e5f6a7b";
    let entity = "7c1e5b60-2f4d-4a3e-8b9c-1d2e3f4a5b6c";

    let applied: MutationResult = serde_json::from_value(json!({
        "mutationId": uuid, "entityType": "ledger.transaction", "entityId": entity,
        "baseRevision": 0, "status": "applied", "revision": 42
    }))
    .expect("applied");
    assert!(matches!(applied, MutationResult::Applied(_)));
    assert_eq!(applied.status(), "applied");

    let conflict: MutationResult = serde_json::from_value(json!({
        "mutationId": uuid, "entityType": "website", "entityId": entity,
        "baseRevision": 6, "status": "conflict", "currentRevision": 9,
        "current": null, "deleted": true
    }))
    .expect("conflict");
    match &conflict {
        MutationResult::Conflict(result) => {
            assert!(result.current.is_null());
            assert!(result.deleted);
            assert_eq!(result.current_revision, 9);
        }
        other => panic!("expected conflict, got {other:?}"),
    }

    let rejected: MutationResult = serde_json::from_value(json!({
        "mutationId": uuid, "entityType": "unknown.entity", "entityId": "not-a-uuid",
        "baseRevision": 0, "status": "rejected", "reason": "unknown_entity_type"
    }))
    .expect("rejected echoes free-form entityType/entityId");
    match &rejected {
        MutationResult::Rejected(result) => {
            assert_eq!(result.entity_type, "unknown.entity");
            assert_eq!(result.entity_id, "not-a-uuid");
            assert_eq!(result.reason, RejectionReason::UnknownEntityType);
        }
        other => panic!("expected rejected, got {other:?}"),
    }

    // Early-return shape: mutationId is null (or a non-UUID string), and only the
    // three documented keys are present.
    let early: MutationResult = serde_json::from_value(json!({
        "mutationId": null, "status": "rejected", "reason": "invalid_id"
    }))
    .expect("early rejected");
    assert!(matches!(early, MutationResult::RejectedEarly(_)));
    assert_eq!(early.mutation_id(), None);

    let early_raw: MutationResult = serde_json::from_value(json!({
        "mutationId": "not-a-uuid", "status": "rejected", "reason": "invalid_id"
    }))
    .expect("early rejected with the raw offending value");
    assert_eq!(early_raw.mutation_id(), Some("not-a-uuid"));

    // The early shape is pinned to invalid_id.
    assert!(serde_json::from_value::<MutationResult>(json!({
        "mutationId": null, "status": "rejected", "reason": "invalid_fields"
    }))
    .is_err());

    // Fields from another branch are unknown fields here.
    assert!(
        serde_json::from_value::<MutationResult>(json!({
            "mutationId": uuid, "status": "applied", "revision": 42
        }))
        .is_err(),
        "applied without entityType/entityId/baseRevision must fail"
    );
    assert!(
        serde_json::from_value::<MutationResult>(json!({
            "mutationId": uuid, "entityType": "website", "entityId": entity,
            "baseRevision": 0, "status": "applied", "revision": 42, "reason": "invalid_data"
        }))
        .is_err(),
        "applied carrying a rejected-only field must fail"
    );
}

#[test]
fn scalar_formats_are_enforced() {
    assert!(Uuid::try_from("7c1e5b60-2f4d-4a3e-8b9c-1d2e3f4a5b6c").is_ok());
    assert!(Uuid::try_from("7C1E5B60-2F4D-4A3E-8B9C-1D2E3F4A5B6C").is_err(), "uppercase");
    assert!(Uuid::try_from("7c1e5b60-2f4d-4a3e-8b9c-1d2e3f4a5b6").is_err(), "short");
    assert!(Uuid::try_from("7c1e5b60_2f4d-4a3e-8b9c-1d2e3f4a5b6c").is_err(), "separator");

    assert!(IsoUtc::try_from("2026-11-15T08:00:00Z").is_ok());
    assert!(IsoUtc::try_from("2026-11-15T08:00:00.123456Z").is_ok());
    // `iso_utc()` emits `+00:00`; both zero-offset spellings must be accepted (§1).
    assert!(IsoUtc::try_from("2026-11-15T03:00:00+00:00").is_ok());
    assert!(IsoUtc::try_from("2026-11-15T03:00:00.123456+00:00").is_ok());
    assert!(IsoUtc::try_from("2026-11-15T03:00:00.1+00:00").is_ok());
    assert!(IsoUtc::try_from("2026-11-15T03:00:00+08:00").is_err(), "non-UTC offset");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00-05:00").is_err(), "non-UTC offset");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00+0000").is_err(), "offset without colon");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00-00:00").is_err(), "negative zero offset");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00+00:00Z").is_err(), "two designators");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00z").is_err(), "lowercase designator");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00.+00:00").is_err(), "empty fraction");
    assert!(IsoUtc::try_from("2026-11-15T03:00:00.1234567+00:00").is_err(), "7 digits");
    assert!(IsoUtc::try_from("2026-11-15 02:30:00").is_err(), "naive / space");
    assert!(IsoUtc::try_from("2026-11-15T08:00:00").is_err(), "missing designator");
    assert!(IsoUtc::try_from("2026-11-15T08:00:00.Z").is_err(), "empty fraction");
    assert!(IsoUtc::try_from("2026-11-15T08:00:00.1234567Z").is_err(), "7 digits");
    assert!(IsoUtc::try_from("2026-13-15T08:00:00Z").is_err(), "month 13");
    assert!(
        IsoUtc::try_from("2026-13-15T08:00:00+00:00").is_err(),
        "range checks apply to both spellings"
    );

    assert!(DecimalString::try_from("38.50").is_ok());
    assert!(DecimalString::try_from("0.01").is_ok());
    assert!(DecimalString::try_from("0").is_ok());
    assert!(DecimalString::try_from("1.234").is_err(), "3 decimals");
    assert!(DecimalString::try_from("038.50").is_err(), "leading zero");
    assert!(DecimalString::try_from("-38.50").is_err(), "negative");
    assert!(DecimalString::try_from("1e3").is_err(), "exponent");
    assert!(DecimalString::try_from("1234567890123").is_err(), "13 integer digits");
    assert!(!DecimalString::try_from("0.00").expect("parses").is_positive());
    assert!(DecimalString::try_from("0.01").expect("parses").is_positive());

    assert!(ClientCredential::try_from("sk_liv...abcd").is_err());
    assert!(ClientCredential::try_from(
        "nc_live_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    )
    .is_ok());
    assert!(TokenLast4::try_from("S9t0").is_ok());
    assert!(TokenLast4::try_from("S9t").is_err());

    assert!(HttpUrl::try_from("https://github.com/zjyzjy0823-hue/Nexa-LumaDock").is_ok());
    assert!(HttpUrl::try_from("ftp://example.com").is_err(), "scheme");
    assert!(HttpUrl::try_from("https://exa mple.com").is_err(), "whitespace");
    assert!(HttpUrl::try_from("http://").is_err(), "scheme without authority");

    assert!(NonEmptyStr::try_from("").is_err());
    assert!(serde_json::from_value::<Revision>(json!(0)).is_err(), "revisions start at 1");
    assert!(serde_json::from_value::<Revision>(json!(1)).is_ok());
    assert!(serde_json::from_value::<BaseRevision>(json!(-1)).is_err());
    assert!(serde_json::from_value::<BaseRevision>(json!(1.5)).is_err());
    assert!(serde_json::from_value::<ProtocolVersion>(json!(2)).is_err());
    assert!(serde_json::from_value::<ProtocolVersion>(json!(3)).is_ok());
}

#[test]
fn every_layer_rejects_unknown_fields() {
    let uuid = "3f9d0d5e-1c4a-4f6e-9a1b-2c3d4e5f6a7b";
    let entity = "7c1e5b60-2f4d-4a3e-8b9c-1d2e3f4a5b6c";
    let rejected: Vec<(&str, Result<(), String>)> = vec![
        (
            "ErrorResponse",
            parse_as("ErrorResponse", json!({"detail": "nope", "extra": 1})),
        ),
        (
            "EnrollmentRequest",
            parse_as(
                "EnrollmentRequest",
                json!({"installationId": "x", "name": "Pixel 9", "platform": "android", "clientId": uuid}),
            ),
        ),
        (
            "ConflictResolution",
            parse_as(
                "ConflictResolution",
                json!({"strategy": "local", "expectedRemoteRevision": 9, "force": true}),
            ),
        ),
        (
            "ChangesResponse",
            parse_as(
                "ChangesResponse",
                json!({"protocolVersion": 3, "changes": [], "cursor": 0, "hasMore": false,
                       "workspaceRevision": 0, "total": 0}),
            ),
        ),
        (
            "SnapshotPage",
            parse_as(
                "SnapshotPage",
                json!({"protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 0,
                       "entities": [], "cursor": null, "hasMore": false, "total": 0}),
            ),
        ),
        (
            "CursorError",
            parse_as(
                "CursorError",
                json!({"detail": "Invalid sync cursor", "resyncRequired": true,
                       "workspaceRevision": 0, "retryAfter": 1}),
            ),
        ),
        (
            "ConflictsResponse",
            parse_as("ConflictsResponse", json!({"conflicts": [], "total": 0})),
        ),
        (
            "MutationsResponse",
            parse_as(
                "MutationsResponse",
                json!({"protocolVersion": 3, "results": [], "cursor": 1}),
            ),
        ),
        (
            "MutationBatch",
            parse_as(
                "MutationBatch",
                json!({"protocolVersion": 3, "mutations": [], "clientId": uuid}),
            ),
        ),
    ];
    for (label, result) in rejected {
        assert!(result.is_err(), "{label} must reject unknown fields");
    }

    // A change must also reject a field that belongs to the response, and vice versa.
    assert!(serde_json::from_value::<Change>(json!({
        "revision": 43, "entityType": "website", "entityId": entity,
        "operation": "delete", "data": null, "hasMore": true
    }))
    .is_err());

    // And a conflict row must not smuggle in the resolution strategy.
    assert!(serde_json::from_value::<ConflictPresentation>(json!({
        "id": "7", "entityType": "website", "entityId": entity,
        "local": null, "localDeleted": false, "remote": null, "remoteRevision": 0,
        "remoteDeleted": true, "createdAt": "2026-11-15T02:00:00Z",
        "updatedAt": "2026-11-15T02:05:00Z", "hasPendingTail": false, "strategy": "local"
    }))
    .is_err());
}

#[test]
fn required_keys_must_be_present_even_when_nullable() {
    // `data`, `current`, `local`, `remote` are required-but-nullable: omitting them is a
    // different document from sending null, and the contract forbids the former.
    let uuid = "3f9d0d5e-1c4a-4f6e-9a1b-2c3d4e5f6a7b";
    let entity = "7c1e5b60-2f4d-4a3e-8b9c-1d2e3f4a5b6c";
    assert!(serde_json::from_value::<Change>(json!({
        "revision": 43, "entityType": "website", "entityId": entity, "operation": "delete"
    }))
    .is_err());
    assert!(serde_json::from_value::<MutationResult>(json!({
        "mutationId": uuid, "entityType": "website", "entityId": entity,
        "baseRevision": 6, "status": "conflict", "currentRevision": 9, "deleted": false
    }))
    .is_err());
    assert!(serde_json::from_value::<ConflictPresentation>(json!({
        "id": "7", "entityType": "website", "entityId": entity,
        "localDeleted": false, "remote": null, "remoteRevision": 0,
        "remoteDeleted": true, "createdAt": "2026-11-15T02:00:00Z",
        "updatedAt": "2026-11-15T02:05:00Z", "hasPendingTail": false
    }))
    .is_err());
    // `SnapshotPage.cursor` is required-but-nullable too: omitting it is not "null".
    assert!(serde_json::from_value::<SnapshotPage>(json!({
        "protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 1,
        "entities": [], "hasMore": false
    }))
    .is_err());
    assert!(serde_json::from_value::<SnapshotEntity>(json!({
        "entityType": "website", "entityId": entity, "syncRevision": 1, "deleted": false
    }))
    .is_err());
}

#[test]
fn batch_size_bounds_are_enforced() {
    let template = |index: usize| {
        json!({
            "mutationId": format!("3f9d0d5e-1c4a-4f6e-9a1b-2c3d4e5f6a{index:02x}"),
            "entityType": "website",
            "entityId": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
            "operation": "delete",
            "baseRevision": 0
        })
    };
    let batch = |count: usize| {
        let mutations: Vec<Value> = (0..count).map(template).collect();
        json!({"protocolVersion": 3, "mutations": mutations})
    };

    assert!(serde_json::from_value::<MutationBatch>(batch(1)).is_ok());
    assert!(serde_json::from_value::<MutationBatch>(batch(100)).is_ok());
    assert!(serde_json::from_value::<MutationBatch>(batch(0)).is_err(), "minItems 1");
    assert!(
        serde_json::from_value::<MutationBatch>(batch(101)).is_err(),
        "maxItems 100"
    );
}

#[test]
fn mutations_response_length_tracks_the_request() {
    // results is `maxItems: 100` and must stay aligned 1:1 with the request order.
    let response: MutationsResponse =
        serde_json::from_value(read_json("samples/valid/mutations-mixed.json"))
            .expect("valid mixed response");
    assert_eq!(response.results.len(), 4);
    let statuses: Vec<&str> = response.results.iter().map(MutationResult::status).collect();
    assert_eq!(statuses, vec!["applied", "conflict", "rejected", "rejected"]);
    assert!(matches!(
        response.results[3],
        MutationResult::RejectedEarly(_)
    ));
    response.validate().expect("mixed response is within bounds");
}

#[test]
fn changes_invariants_accept_the_valid_pages() {
    let page: ChangesResponse =
        serde_json::from_value(read_json("samples/valid/changes-page.json")).expect("page");
    page.validate().expect("valid page satisfies SR-5..SR-7");
    assert_eq!(page.cursor, 44);
    assert_eq!(page.workspace_revision, 120);
    assert!(page.has_more);
    assert!(!page.is_caught_up());
    assert_eq!(page.changes.len(), 2);
    assert_eq!(page.changes[0].revision.get(), 43);
    assert_eq!(page.changes[1].operation, Operation::Delete);
    assert!(page.changes[1].data.is_none());

    let empty: ChangesResponse =
        serde_json::from_value(read_json("samples/valid/changes-empty.json")).expect("empty page");
    empty.validate().expect("empty page echoes the request cursor");
    assert!(empty.is_caught_up(), "cursor == workspaceRevision, hasMore=false");

    // §1: the server currently emits `+00:00` (`iso_utc()`). Such a page must be
    // accepted verbatim, and its payloads must pass SR-2 — that is the layer where
    // the timestamp format is actually checked.
    let offset: ChangesResponse =
        serde_json::from_value(read_json("samples/valid/changes-page-offset-timestamps.json"))
            .expect("`+00:00` timestamps are contract-valid");
    offset
        .validate()
        .expect("the offset page satisfies the same SR-5..SR-7 invariants");
    assert_eq!(offset.changes.len(), 2);
    assert_eq!(
        offset.changes[0].data.as_ref().expect("upsert data")["occurredAt"],
        json!("2026-11-15T02:30:00+00:00"),
        "the fixture must keep exercising the `+00:00` spelling"
    );
    let payload = offset.changes[0]
        .entity_payload()
        .expect("a `+00:00` payload is valid")
        .expect("upsert carries data");
    assert_eq!(payload.entity_type(), EntityType::LedgerTransaction);
}

#[test]
fn snapshot_pages_are_typed_and_enforce_tombstone_pairing() {
    let page: SnapshotPage =
        serde_json::from_value(read_json("samples/valid/snapshot-page.json")).expect("snapshot");
    page.validate().expect("the valid page satisfies §11.2");
    assert_eq!(page.protocol_version.get(), SYNC_PROTOCOL_VERSION);
    assert_eq!(page.workspace_revision, 44);
    assert!(page.has_more);
    assert!(page.cursor.is_some(), "hasMore=true requires a cursor");
    assert_eq!(page.entities.len(), 3);
    assert_eq!(page.entities[0].entity_type, EntityType::LedgerCategory);
    assert_eq!(page.entities[0].sync_revision.get(), 41);
    assert!(!page.entities[0].deleted);

    // Live rows carry the same payload shapes `/changes` does (SR-2).
    let category = page.entities[0]
        .entity_payload()
        .expect("live category payload")
        .expect("live rows carry data");
    assert_eq!(category.entity_type(), EntityType::LedgerCategory);
    let website = page.entities[1]
        .entity_payload()
        .expect("live website payload")
        .expect("live rows carry data");
    assert_eq!(website.entity_type(), EntityType::Website);

    // Tombstone: deleted=true + data=null, and no payload to validate.
    let tombstone = &page.entities[2];
    assert!(tombstone.deleted);
    assert!(tombstone.data.is_none());
    assert!(tombstone
        .entity_payload()
        .expect("tombstones have no payload")
        .is_none());

    // The envelope rejects both wrong pairings, in either direction.
    let mut live_with_null = read_json("samples/valid/snapshot-page.json");
    live_with_null["entities"][0]["data"] = Value::Null;
    assert!(
        serde_json::from_value::<SnapshotPage>(live_with_null).is_err(),
        "deleted=false with data=null must be rejected"
    );
    let mut tombstone_with_data = read_json("samples/valid/snapshot-page.json");
    tombstone_with_data["entities"][2]["data"] = json!({"name": "ghost"});
    assert!(
        serde_json::from_value::<SnapshotPage>(tombstone_with_data).is_err(),
        "deleted=true with an object data must be rejected"
    );

    // `cursor` is null exactly when `hasMore` is false (§11.2).
    let mut dangling_cursor = read_json("samples/valid/snapshot-page.json");
    dangling_cursor["hasMore"] = json!(false);
    let dangling: SnapshotPage =
        serde_json::from_value(dangling_cursor).expect("shape is valid, only the invariant breaks");
    assert_eq!(
        dangling.validate().expect_err("cursor without hasMore").rule,
        "§11.2"
    );

    let mut null_cursor = read_json("samples/valid/snapshot-page.json");
    null_cursor["cursor"] = Value::Null;
    let null_cursor: SnapshotPage =
        serde_json::from_value(null_cursor).expect("cursor: null is legal");
    assert_eq!(
        null_cursor.validate().expect_err("hasMore without cursor").rule,
        "§11.2"
    );

    // An entity cannot be newer than the revision the snapshot pinned.
    let mut too_new = read_json("samples/valid/snapshot-page.json");
    too_new["entities"][0]["syncRevision"] = json!(45);
    let too_new: SnapshotPage = serde_json::from_value(too_new).expect("shape is valid");
    assert_eq!(
        too_new.validate().expect_err("syncRevision > workspaceRevision").rule,
        "§11.2"
    );

    // The final page of a paging run: empty entities, cursor null, hasMore false.
    let final_page: SnapshotPage = serde_json::from_value(json!({
        "protocolVersion": 3,
        "snapshotId": "s",
        "workspaceRevision": 44,
        "entities": [],
        "cursor": null,
        "hasMore": false
    }))
    .expect("empty final page");
    final_page.validate().expect("empty final page is valid");

    // A page can never exceed `limit` (500) rows.
    let oversized: Vec<Value> = (0..501)
        .map(|index| {
            json!({
                "entityType": "website",
                "entityId": format!("1a2b3c4d-5e6f-4a7b-8c9d-{index:012x}"),
                "syncRevision": 1,
                "deleted": true,
                "data": null
            })
        })
        .collect();
    assert!(
        serde_json::from_value::<SnapshotPage>(json!({
            "protocolVersion": 3, "snapshotId": "s", "workspaceRevision": 1,
            "entities": oversized, "cursor": "c", "hasMore": true
        }))
        .is_err(),
        "maxItems 500"
    );
}

#[test]
fn cursor_error_body_is_pinned() {
    let value = read_json("samples/valid/cursor-error.json");
    let error: CursorError = serde_json::from_value(value.clone()).expect("cursor error body");
    assert_eq!(error.detail, details::INVALID_SYNC_CURSOR);
    assert!(error.resync_required);
    assert_eq!(error.workspace_revision, 44);
    assert_eq!(
        serde_json::to_value(&error).expect("serialize CursorError"),
        value,
        "the 400 body must round-trip unchanged"
    );

    for broken in [
        json!({"detail": "Invalid sync cursor", "resyncRequired": false, "workspaceRevision": 44}),
        json!({"detail": "nope", "resyncRequired": true, "workspaceRevision": 44}),
        json!({"detail": "Invalid sync cursor", "resyncRequired": true, "workspaceRevision": 44,
               "extra": 1}),
        json!({"detail": "Invalid sync cursor", "workspaceRevision": 44}),
        json!({"detail": "Invalid sync cursor", "resyncRequired": true, "workspaceRevision": -1}),
    ] {
        assert!(
            serde_json::from_value::<CursorError>(broken.clone()).is_err(),
            "must reject {broken}"
        );
    }
}

#[test]
fn entity_payloads_accept_the_documented_shapes() {
    let ledger: EntityPayload = parse_entity_data(
        EntityType::LedgerTransaction,
        &json!({
            "categoryId": "2b3c4d5e-6f70-4182-93a4-b5c6d7e8f901",
            "type": "expense",
            "amount": "38.50",
            "description": "咖啡",
            "merchant": "Manner",
            "note": "",
            "occurredAt": "2026-11-15T02:30:00Z"
        }),
    )
    .expect("ledger.transaction payload");
    assert_eq!(ledger.entity_type(), EntityType::LedgerTransaction);

    let website: EntityPayload = parse_entity_data(
        EntityType::Website,
        &json!({
            "name": "Nexa Roadmap",
            "url": "https://github.com/zjyzjy0823-hue/Nexa-LumaDock",
            "icon": null,
            "description": "规划文档",
            "categoryId": null,
            "favorite": true,
            "order": 0,
            "lastVisitedAt": "2026-11-15T03:00:00Z",
            "createdAt": "2026-10-01T00:00:00Z",
            "updatedAt": "2026-11-15T03:00:00Z"
        }),
    )
    .expect("website payload");
    assert_eq!(website.entity_type(), EntityType::Website);

    let preferences: EntityPayload = parse_entity_data(
        EntityType::UserPreferences,
        &json!({"theme": "dark", "language": "zh-CN", "timezone": "Asia/Shanghai"}),
    )
    .expect("personal state payload");
    assert_eq!(preferences.entity_type(), EntityType::UserPreferences);

    // Payload-level rejections: unknown key, bad enum, number-typed amount, missing key.
    for (entity_type, payload) in [
        (
            EntityType::LedgerTransaction,
            json!({"type": "expense", "amount": "38.50", "description": "咖啡",
                   "occurredAt": "2026-11-15T02:30:00Z", "clientId": "x"}),
        ),
        (
            EntityType::LedgerTransaction,
            json!({"type": "transfer", "amount": "38.50", "description": "咖啡",
                   "occurredAt": "2026-11-15T02:30:00Z"}),
        ),
        (
            EntityType::LedgerTransaction,
            json!({"type": "expense", "amount": 38.5, "description": "咖啡",
                   "occurredAt": "2026-11-15T02:30:00Z"}),
        ),
        (
            EntityType::Website,
            json!({"name": "Nexa Roadmap"}),
        ),
        (EntityType::DataRecord, json!({"name": "no collectionId"})),
    ] {
        assert!(
            parse_entity_data(entity_type, &payload).is_err(),
            "payload should be rejected for {entity_type}: {payload}"
        );
    }
}

#[test]
fn conflicts_and_enrollment_samples_are_typed() {
    let conflicts: ConflictsResponse =
        serde_json::from_value(read_json("samples/valid/conflicts-list.json")).expect("conflicts");
    assert_eq!(conflicts.conflicts.len(), 1);
    let row = &conflicts.conflicts[0];
    assert_eq!(row.id.as_str(), "7");
    assert!(!row.local.is_null() && !row.remote.is_null());
    assert_eq!(row.remote_revision, 9);
    assert!(row.has_pending_tail);

    let enrollment: EnrollmentResponse =
        serde_json::from_value(read_json("samples/valid/enrollment-response.json")).expect("enroll");
    assert_eq!(enrollment.token_last4.as_str(), "S9t0");
    assert_eq!(enrollment.token_created_at.as_str(), "2026-11-15T08:00:00Z");
    assert!(enrollment.credential.as_str().starts_with("nc_live_"));
    assert_eq!(enrollment.client.platform, "android");

    let resolution: ConflictResolution =
        serde_json::from_value(read_json("samples/valid/conflict-resolution.json")).expect("resolve");
    assert_eq!(resolution.strategy, ConflictStrategy::Remote);
    assert_eq!(
        resolution.expected_remote_revision.map(BaseRevision::get),
        Some(9)
    );

    let optional: ConflictResolution =
        serde_json::from_value(json!({"strategy": "local"})).expect("strategy only");
    assert!(optional.expected_remote_revision.is_none());
}

#[test]
fn error_bodies_round_trip() {
    let error: ErrorResponse =
        serde_json::from_value(read_json("samples/valid/error-response.json")).expect("error body");
    assert_eq!(error.detail.as_str(), "sync_protocol_mismatch");
    let mut map = Map::new();
    map.insert(
        "detail".to_owned(),
        Value::String(details::INVALID_SYNC_CURSOR.to_owned()),
    );
    let typed: ErrorResponse = serde_json::from_value(Value::Object(map)).expect("cursor error");
    assert_eq!(typed.detail.as_str(), "Invalid sync cursor");
}
