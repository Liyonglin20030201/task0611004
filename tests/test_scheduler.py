"""定时调度测试"""

from log_inspector.config import TaskConfig
from log_inspector.db import Database


class TestScheduleLock:
    def test_acquire_lock_success(self, db):
        assert db.acquire_schedule_lock("task1", "202606101000") is True

    def test_acquire_lock_duplicate(self, db):
        db.acquire_schedule_lock("task1", "202606101000")
        assert db.acquire_schedule_lock("task1", "202606101000") is False

    def test_different_windows_ok(self, db):
        assert db.acquire_schedule_lock("task1", "202606101000") is True
        assert db.acquire_schedule_lock("task1", "202606101001") is True

    def test_release_lock(self, db):
        db.acquire_schedule_lock("task1", "202606101000")
        db.release_schedule_lock("task1", "202606101000", "completed")

        # Verify status updated
        with db.connect() as conn:
            row = conn.execute(
                "SELECT status, finished_at FROM schedule_runs WHERE lock_key=?",
                ("task1:202606101000",)
            ).fetchone()
            assert row["status"] == "completed"
            assert row["finished_at"] is not None


class TestScheduleManager:
    def test_add_task(self, db):
        from log_inspector.scheduler import ScheduleManager
        manager = ScheduleManager(db)
        task = TaskConfig(name="test_task", cron="0 * * * *", log_sources=["/tmp/test.log"])
        manager.add_task(task)
        jobs = manager.list_tasks()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "test_task"
        assert jobs[0]["cron"] == "0 * * * *"
        assert jobs[0]["log_sources"] == ["/tmp/test.log"]
        assert jobs[0]["enabled"] is True

    def test_remove_task(self, db):
        from log_inspector.scheduler import ScheduleManager
        manager = ScheduleManager(db)
        task = TaskConfig(name="test_task", cron="0 * * * *", log_sources=["/tmp/test.log"])
        manager.add_task(task)
        manager.remove_task("test_task")
        assert len(manager.list_tasks()) == 0

    def test_duplicate_task_skipped(self, db):
        from log_inspector.scheduler import ScheduleManager
        manager = ScheduleManager(db)
        task = TaskConfig(name="dup", cron="0 * * * *", log_sources=["/tmp/test.log"])
        manager.add_task(task)
        manager.add_task(task)  # Should not raise
        jobs = manager.list_tasks()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "dup"

    def test_list_multiple_tasks_stable(self, db):
        """多任务注册后列表稳定显示所有条目"""
        from log_inspector.scheduler import ScheduleManager
        manager = ScheduleManager(db)
        for i in range(5):
            task = TaskConfig(name=f"task_{i}", cron=f"{i * 10} * * * *", log_sources=[f"/log/{i}.log"])
            manager.add_task(task)

        jobs = manager.list_tasks()
        assert len(jobs) == 5
        names = {j["name"] for j in jobs}
        assert names == {"task_0", "task_1", "task_2", "task_3", "task_4"}

    def test_duplicate_different_cron_still_skipped(self, db):
        """同名任务即使 cron 不同，也不会重复注册"""
        from log_inspector.scheduler import ScheduleManager
        manager = ScheduleManager(db)
        task1 = TaskConfig(name="same", cron="0 * * * *", log_sources=["/a.log"])
        task2 = TaskConfig(name="same", cron="*/5 * * * *", log_sources=["/b.log"])
        manager.add_task(task1)
        manager.add_task(task2)
        jobs = manager.list_tasks()
        assert len(jobs) == 1
        assert jobs[0]["cron"] == "0 * * * *"  # 保留第一次注册的
