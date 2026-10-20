"""Shared generator fixtures: one small population and plan, built once per test session."""

from pathlib import Path

import pytest

from mailspider.generator.config import GeneratorConfig
from mailspider.generator.model import PlannedMail, RenderedMail, stage_rng
from mailspider.generator.planner import plan
from mailspider.generator.population import Population, build_population
from mailspider.generator.render import render

PLAN_MAILS = 4000
RENDER_STEP = 8


def small_config(tmp: Path, **changes: object) -> GeneratorConfig:
    """A configuration for tests; out_dir and meta_dir below `tmp`."""
    values: dict[str, object] = {
        "out_dir": tmp / "mbox",
        "meta_dir": tmp / "mbox" / "_generator",
        "mails": PLAN_MAILS,
        "large_attachments": 1,
        "large_attachment_size": 3 * 1024**2,
    }
    values.update(changes)
    return GeneratorConfig(**values)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def gen_config(tmp_path_factory: pytest.TempPathFactory) -> GeneratorConfig:
    return small_config(tmp_path_factory.mktemp("generator"))


@pytest.fixture(scope="session")
def gen_population(gen_config: GeneratorConfig) -> Population:
    return build_population(gen_config, stage_rng(gen_config.seed, "population"))


@pytest.fixture(scope="session")
def gen_plan(gen_config: GeneratorConfig, gen_population: Population) -> list[PlannedMail]:
    return list(plan(gen_config, gen_population))


@pytest.fixture(scope="session")
def gen_rendered(gen_plan: list[PlannedMail]) -> list[RenderedMail]:
    """Every RENDER_STEP-th planned mail, spread over the whole date range, and the large ones."""
    sample = [m for m in gen_plan if m.index % RENDER_STEP == 0 or m.large_attachment]
    return [render(mail) for mail in sample]
