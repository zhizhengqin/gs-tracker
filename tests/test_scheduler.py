"""Tests for src.scheduler."""

import asyncio
import logging
import signal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.scheduler import GSScheduler


def test_schedule_quarterly_check_creates_monday_job():
    scheduler = GSScheduler()
    scheduler.schedule_quarterly_check()
    job = scheduler.scheduler.get_job("quarterly_check")
    assert job is not None

    field_map = {f.name: str(f) for f in job.trigger.fields}
    assert field_map["day_of_week"] == "mon"
    assert field_map["hour"] == "9"
    assert field_map["minute"] == "0"
    assert str(job.trigger.timezone) == "Asia/Shanghai"
    scheduler.shutdown()


@pytest.mark.asyncio
async def test_run_quarterly_pipeline_delegates_to_run_pipeline(monkeypatch):
    scheduler = GSScheduler()
    mock_pipeline = AsyncMock()
    monkeypatch.setattr("src.main.run_pipeline", mock_pipeline)

    await scheduler.run_quarterly_pipeline()
    mock_pipeline.assert_awaited_once()
    scheduler.shutdown()


@pytest.mark.asyncio
async def test_run_quarterly_pipeline_swallows_exception(monkeypatch, caplog):
    scheduler = GSScheduler()
    mock_pipeline = AsyncMock(side_effect=RuntimeError("pipeline failed"))
    monkeypatch.setattr("src.main.run_pipeline", mock_pipeline)

    caplog.set_level(logging.ERROR)
    await scheduler.run_quarterly_pipeline()

    mock_pipeline.assert_awaited_once()
    assert any("pipeline failed" in record.message for record in caplog.records)
    scheduler.shutdown()


@pytest.mark.asyncio
async def test_main_lifecycle_starts_and_shuts_down(monkeypatch):
    from src import scheduler as scheduler_module

    mock_scheduler_instance = MagicMock()
    mock_scheduler_instance.start = MagicMock()
    mock_scheduler_instance.shutdown = MagicMock()

    mock_scheduler_class = MagicMock(return_value=mock_scheduler_instance)
    monkeypatch.setattr(scheduler_module, "GSScheduler", mock_scheduler_class)

    shutdown_event = asyncio.Event()

    async def _stop_later():
        shutdown_event.set()

    asyncio.create_task(_stop_later())

    await scheduler_module.main(shutdown_event=shutdown_event)

    mock_scheduler_class.assert_called_once()
    mock_scheduler_instance.schedule_quarterly_check.assert_called_once()
    mock_scheduler_instance.start.assert_called_once()
    mock_scheduler_instance.shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_main_registers_signal_handlers(monkeypatch):
    from src import scheduler as scheduler_module

    added = {}
    removed = []

    def mock_add_signal_handler(sig, handler):
        added[sig] = handler

    def mock_remove_signal_handler(sig):
        removed.append(sig)
        return True

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", mock_add_signal_handler)
    monkeypatch.setattr(loop, "remove_signal_handler", mock_remove_signal_handler)

    mock_scheduler_instance = MagicMock()
    mock_scheduler_instance.start = MagicMock()
    mock_scheduler_instance.shutdown = MagicMock()
    monkeypatch.setattr(
        scheduler_module, "GSScheduler", MagicMock(return_value=mock_scheduler_instance)
    )

    shutdown_event = asyncio.Event()

    async def _stop_later():
        shutdown_event.set()

    asyncio.create_task(_stop_later())

    await scheduler_module.main(shutdown_event=shutdown_event)

    assert signal.SIGINT in added
    assert signal.SIGTERM in added
    assert signal.SIGINT in removed
    assert signal.SIGTERM in removed


@pytest.mark.asyncio
async def test_main_run_now_flag_triggers_pipeline(monkeypatch):
    """--run-now should execute pipeline immediately before entering the wait loop."""
    from src import scheduler as scheduler_module

    mock_scheduler_instance = MagicMock()
    mock_scheduler_instance.run_quarterly_pipeline = AsyncMock()
    mock_scheduler_instance.start = MagicMock()
    mock_scheduler_instance.shutdown = MagicMock()

    mock_scheduler_class = MagicMock(return_value=mock_scheduler_instance)
    monkeypatch.setattr(scheduler_module, "GSScheduler", mock_scheduler_class)

    shutdown_event = asyncio.Event()

    async def _stop_later():
        shutdown_event.set()

    asyncio.create_task(_stop_later())

    await scheduler_module.main(shutdown_event=shutdown_event, run_now=True)

    mock_scheduler_instance.run_quarterly_pipeline.assert_awaited_once()
    # Scheduler should still start and schedule after the immediate run
    mock_scheduler_instance.schedule_quarterly_check.assert_called_once()
    mock_scheduler_instance.start.assert_called_once()


@pytest.mark.asyncio
async def test_main_calls_ensure_directories(monkeypatch):
    """Scheduler should create output directories on startup for fresh deployments."""
    from src import scheduler as scheduler_module

    mock_ensure = MagicMock()
    monkeypatch.setattr(scheduler_module, "ensure_directories", mock_ensure)

    mock_scheduler_instance = MagicMock()
    mock_scheduler_instance.start = MagicMock()
    mock_scheduler_instance.shutdown = MagicMock()
    monkeypatch.setattr(
        scheduler_module, "GSScheduler", MagicMock(return_value=mock_scheduler_instance)
    )

    shutdown_event = asyncio.Event()

    async def _stop_later():
        shutdown_event.set()

    asyncio.create_task(_stop_later())

    await scheduler_module.main(shutdown_event=shutdown_event)

    mock_ensure.assert_called_once()
