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
        self.assertEqual(publish_video(succeeded, "private://video.mp4").approval_state,
                         ApprovalState.PENDING)

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


if __name__ == "__main__":
    unittest.main()
