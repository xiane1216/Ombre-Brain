"""
========================================
snapshot_history.py — 写前快照历史
========================================

在 update/delete 等写操作执行前自动保存桶的当前版本。
保护粒度从「天」进化到「每一次写入」——手滑覆盖了能一秒找回。

对外暴露：SnapshotHistory 类（save_snapshot / get_snapshots / get_snapshot / restore_snapshot）
========================================
"""

import os
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("ombre_brain.snapshot")


class SnapshotHistory:
    """写前快照历史管理器。每次修改前自动存档，按桶ID和时间查询。"""

    def __init__(self, buckets_dir: str):
        db_path = os.path.join(buckets_dir, "_ledger", "snapshots.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_id TEXT NOT NULL,
                name TEXT DEFAULT '',
                content TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                snapshot_at TEXT NOT NULL,
                operation TEXT NOT NULL DEFAULT 'update',
                reason TEXT DEFAULT ''
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_bucket_id
            ON snapshots(bucket_id)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshots_at
            ON snapshots(snapshot_at)
        """)
        self._conn.commit()

    def save_snapshot(
        self,
        bucket_id: str,
        content: str,
        metadata: Optional[dict] = None,
        operation: str = "update",
        reason: str = "",
    ) -> int:
        """
        保存当前桶的快照。返回快照ID。
        每次写操作前调用——先拍快照，再执行修改。
        """
        name = (metadata or {}).get("name", "") if metadata else ""
        now = datetime.now().isoformat()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        cursor = self._conn.execute(
            "INSERT INTO snapshots (bucket_id, name, content, metadata_json, snapshot_at, operation, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bucket_id, name, content, meta_json, now, operation, reason),
        )
        self._conn.commit()
        snap_id = cursor.lastrowid
        logger.info(f"快照已保存: {bucket_id} (操作:{operation}) → id={snap_id}")
        return snap_id

    def get_snapshots(
        self,
        bucket_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """查询某个桶的快照历史，按时间倒序。"""
        rows = self._conn.execute(
            "SELECT id, bucket_id, name, content, metadata_json, snapshot_at, operation, reason FROM snapshots WHERE bucket_id = ? ORDER BY snapshot_at DESC LIMIT ?",
            (bucket_id, limit),
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "bucket_id": row[1],
                "name": row[2],
                "content": row[3],
                "metadata": json.loads(row[4]) if row[4] else {},
                "snapshot_at": row[5],
                "operation": row[6],
                "reason": row[7],
            })
        return result

    def get_snapshot(self, snapshot_id: int) -> Optional[dict]:
        """按快照ID查询单个快照。"""
        row = self._conn.execute(
            "SELECT id, bucket_id, name, content, metadata_json, snapshot_at, operation, reason FROM snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "bucket_id": row[1],
            "name": row[2],
            "content": row[3],
            "metadata": json.loads(row[4]) if row[4] else {},
            "snapshot_at": row[5],
            "operation": row[6],
            "reason": row[7],
        }

    def get_all_snapshots(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """全局快照列表，按时间倒序。"""
        rows = self._conn.execute(
            "SELECT id, bucket_id, name, content, metadata_json, snapshot_at, operation, reason FROM snapshots ORDER BY snapshot_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "id": row[0],
                "bucket_id": row[1],
                "name": row[2],
                "content": row[3],
                "metadata": json.loads(row[4]) if row[4] else {},
                "snapshot_at": row[5],
                "operation": row[6],
                "reason": row[7],
            })
        return result

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
