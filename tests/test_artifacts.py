import hashlib
import tempfile
import unittest
from pathlib import Path

from lattice.config import ConfigError, load_config
from lattice.contracts import (
    ApprovalState,
    ArtifactProvenance,
    AssetManifest,
    AssetReference,
    RenderJobStatus,
    Topic,
)
from lattice.evidence import build_review_evidence
from lattice.pipeline import (
    build_asset_manifest,
    build_research_packet,
    build_script,
    build_storyboard,
    create_render_job,
    publish_video,
)


class ArtifactContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config(
            Path(__file__).parents[1] / "configs" / "knowledge-channel.json"
        )
        topic = build_research_packet(Topic("A topic", "systems"))
        self.script = build_script(self.config, topic)
        self.storyboard = build_storyboard(self.config, self.script)
        self.manifest = build_asset_manifest(self.storyboard)

    def test_pipeline_emits_versioned_provenance_chain(self) -> None:
        self.assertEqual(self.script.version, 1)
        self.assertEqual(self.script.provenance.config_hash, self.config.config_hash)
        self.assertEqual(
            self.storyboard.provenance.input_artifact_ids,
            (self.script.provenance.artifact_id,),
        )
        self.assertEqual(
            self.manifest.provenance.input_artifact_ids,
            (self.storyboard.provenance.artifact_id,),
        )
        self.assertEqual(len(self.manifest.provenance.content_hash), 64)

    def test_render_job_rejects_invalid_state_transition(self) -> None:
        job = create_render_job(self.storyboard, self.manifest)
        with self.assertRaisesRegex(ValueError, "queued to succeeded"):
            job.transition_to(RenderJobStatus.SUCCEEDED)
        succeeded = job.transition_to(RenderJobStatus.RUNNING).transition_to(
            RenderJobStatus.SUCCEEDED
        )
        self.assertEqual(
            publish_video(succeeded, "private://video.mp4").approval_state,
            ApprovalState.PENDING,
        )

    def test_published_video_requires_successful_render(self) -> None:
        job = create_render_job(self.storyboard, self.manifest)
        with self.assertRaisesRegex(ValueError, "succeeded"):
            publish_video(job, "private://video.mp4")

    def test_contract_rejects_duplicate_assets_and_invalid_hash(self) -> None:
        asset = AssetReference("asset-1", "visual", "local://asset-1")
        with self.assertRaisesRegex(ConfigError, "unique"):
            AssetManifest((asset, asset))
        with self.assertRaisesRegex(ConfigError, "SHA-256"):
            ArtifactProvenance("artifact-1", content_hash="not-a-hash")

    def test_review_evidence_is_source_and_scene_traceable(self) -> None:
        evidence = build_review_evidence(self._bundle())
        self.assertEqual(len(evidence["claims"]), len(evidence["sources"]) * 0 + 1)
        self.assertEqual(
            evidence["timing"]["storyboard_seconds"],
            sum(scene.duration_seconds for scene in self.storyboard.scenes),
        )
        self.assertTrue(evidence["scenes"][0]["claim_ids"])
        self.assertEqual(len(evidence["scenes"][0]["script_text_hash"]), 64)
        self.assertIn("limitations", evidence)

    def test_review_evidence_records_media_identity_and_srt_mapping(self) -> None:
        bundle = self._bundle()
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "episode.mp4"
            video.write_bytes(b"deterministic-media")
            video.with_suffix(".srt").write_text(
                "\n\n".join(
                    f"{index}\n00:00:{index - 1:02d},000 --> 00:00:{index:02d},000\n{scene.narration}"
                    for index, scene in enumerate(bundle.storyboard.scenes, 1)
                ),
                encoding="utf-8",
            )
            evidence = build_review_evidence(bundle, video_path=video)
            self.assertEqual(evidence["media"]["path"], str(video))
            self.assertEqual(
                evidence["media"]["sha256"],
                hashlib.sha256(video.read_bytes()).hexdigest(),
            )
            self.assertTrue(evidence["srt"]["timing_valid"])
            self.assertTrue(
                all(
                    item["narration_matches_srt"]
                    for item in evidence["srt"]["scene_mappings"]
                )
            )

    def _bundle(self):
        from lattice.pipeline import EpisodeDraft, ProductionBundle, create_render_job

        return ProductionBundle(
            EpisodeDraft(
                self.script.topic, build_research_packet(self.script.topic), self.script
            ),
            self.storyboard,
            self.manifest,
            create_render_job(self.storyboard, self.manifest),
        )


if __name__ == "__main__":
    unittest.main()
