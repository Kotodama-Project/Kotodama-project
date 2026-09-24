// Synthetic operator input only. No source transcripts or Task records are imported.
export function syntheticSeed() {
  return {
    actor: { subject: "reviewer-synthetic", email: "reviewer@example.test" },
    projection: {
      schema: "kotodama.cloudflare_os.authorized_voice_projection",
      schema_version: "1.0.0",
      route: "cloudflare_os->context_gateway",
      data_class: "authorized_voice_handoff_projection",
      authority: "candidate_only",
      handoff_id: "handoff-synthetic-1",
      revision: 1,
      overview: "合成会話の review 候補です。",
      speaker_highlights: [{ summary: "候補の内容を確認する。", speaker_ref: "speaker-a" }],
      decisions: [{ summary: "公開は保留。" }],
      todos: [{ summary: "合成候補を review する。", owner: "speaker-a" }],
      open_questions: [{ summary: "次に確認する内容は何か。" }],
      evidence_pointers: [`urn:kotodama:evidence:sha256:${"a".repeat(64)}`],
      human_review: { required: true, state: "pending", actions: ["accept", "edit", "reject"] },
      raw_audio_transferred: false,
      private_transcript_transferred: false,
      context_gateway_bypass: false,
      promotion: false,
      current_truth_mutation: false,
      public_beta: "NO_GO_UNPUBLISHED",
    },
  };
}
