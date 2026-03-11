from __future__ import annotations


def test_public_package_exports() -> None:
    import llm_batch_annotate as package
    from llm_batch_annotate.cli import main as cli_main

    assert package.RunConfig.__name__ == "RunConfig"
    assert package.RunManifest.__name__ == "RunManifest"
    assert package.OpenAIBatchConfig.__name__ == "OpenAIBatchConfig"
    assert package.OpenAIBatchProvider.__name__ == "OpenAIBatchProvider"
    assert package.BaseTask.__name__ == "BaseTask"
    assert package.BaseBuilder.__name__ == "BaseBuilder"
    assert package.BaseOutputParser.__name__ == "BaseOutputParser"
    assert package.ExecutionProviderBase.__name__ == "ExecutionProviderBase"
    assert package.LocalArtifactStore.__name__ == "LocalArtifactStore"
    assert package.SingleTaskBase.__name__ == "SingleTaskBase"
    assert package.GroupedTaskBase.__name__ == "GroupedTaskBase"
    assert package.OfflineTaskPipeline.__name__ == "OfflineTaskPipeline"
    assert package.TaskOrchestrator.__name__ == "TaskOrchestrator"
    assert package.SimpleTemplateBuilder.__name__ == "SimpleTemplateBuilder"
    assert package.StructuredOutputParser.__name__ == "StructuredOutputParser"
    assert package.RawResultRecord.__name__ == "RawResultRecord"
    assert package.normalize_execution_status.__name__ == "normalize_execution_status"
    assert package.artifact_path.__name__ == "artifact_path"
    assert cli_main.__name__ == "main"
