"""HTTP REST API for NormaCore Station — used by N8N workflows and Lovable dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .session import get_session
from .vla_bridge import get_vla_bridge

logger = logging.getLogger("norma-station-http")

app = FastAPI(title="NormaCore Station API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error(exc: Exception, status: int = 500) -> dict[str, Any]:
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": str(exc)}, status_code=status)


# ── Request models ──────────────────────────────────────────────────────────


class BusRequest(BaseModel):
    bus_serial: str = "auto"


class MoveJointRequest(BaseModel):
    joint_id: int
    position: float = Field(ge=0.0, le=1.0)
    bus_serial: str = "auto"


class MovePoseRequest(BaseModel):
    joint_positions: dict[int, float]
    bus_serial: str = "auto"


class MoveVerifiedRequest(BaseModel):
    joint_positions: dict[int, float]
    tolerance_steps: int | None = None
    settle_seconds: float | None = None
    bus_serial: str = "auto"


class GripperRequest(BaseModel):
    position: float = Field(ge=0.0, le=1.0)
    bus_serial: str = "auto"


class PickRequest(BaseModel):
    approach_positions: dict[int, float]
    grasp_positions: dict[int, float] | None = None
    lift_positions: dict[int, float] | None = None
    bus_serial: str = "auto"


class PlaceRequest(BaseModel):
    place_positions: dict[int, float]
    retreat_positions: dict[int, float] | None = None
    bus_serial: str = "auto"


class VLALoadRequest(BaseModel):
    checkpoint_path: str
    device: str = ""


class VLAStepRequest(BaseModel):
    task: str
    n_steps: int = 10
    bus_serial: str = "auto"
    max_delta_ticks: int = 200


class N8NAlertRequest(BaseModel):
    alert_type: str
    message: str
    severity: str = "info"
    stage: str = ""
    timestamp: str = ""


# ── Read endpoints (GET) ───────────────────────────────────────────────────


@app.get("/api/connection")
async def connection_status():
    session = get_session()
    try:
        await session.ensure_connected()
    except Exception as exc:
        return _error(exc, 502)
    return session.connection_info()


@app.get("/api/state")
async def arm_state(bus_serial: str = Query("auto")):
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_inference()
        return session.get_arm_state(bus_serial)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/state/full")
async def full_observation(bus_serial: str = Query("auto")):
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_inference()
        return session.get_full_observation(bus_serial)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/camera")
async def camera_image():
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_normvla(timeout_s=10.0)
        return session.get_camera_image()
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/health")
async def motor_health(bus_serial: str = Query("auto")):
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_inference()
        return session.get_motor_health(bus_serial)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/planning")
async def planning_state(bus_serial: str = Query("auto")):
    session = get_session()
    try:
        return await session.get_planning_state(bus_serial)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/history")
async def action_history(limit: int = Query(10, ge=1, le=100)):
    session = get_session()
    return session.get_action_history(limit)


@app.get("/api/buses")
async def list_buses():
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_inference()
        return session.list_buses()
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/vla/status")
async def vla_status():
    bridge = get_vla_bridge()
    return bridge.status()


# ── Write endpoints (POST) ─────────────────────────────────────────────────


@app.post("/api/move/joint")
async def move_joint(req: MoveJointRequest):
    session = get_session()
    try:
        return await session.move_joint(req.joint_id, req.position, req.bus_serial)
    except ValueError as exc:
        return _error(exc, 400)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/move/pose")
async def move_pose(req: MovePoseRequest):
    session = get_session()
    try:
        return await session.move_arm_pose(req.joint_positions, req.bus_serial)
    except ValueError as exc:
        return _error(exc, 400)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/move/verified")
async def move_verified(req: MoveVerifiedRequest):
    session = get_session()
    try:
        return await session.move_and_verify(
            req.joint_positions, req.tolerance_steps, req.settle_seconds, req.bus_serial,
        )
    except ValueError as exc:
        return _error(exc, 400)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/gripper")
async def set_gripper(req: GripperRequest):
    session = get_session()
    try:
        return await session.set_gripper(req.position, req.bus_serial)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/gripper/open")
async def open_gripper(req: BusRequest | None = None):
    session = get_session()
    bus = req.bus_serial if req else "auto"
    try:
        return await session.open_gripper(bus)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/gripper/close")
async def close_gripper(req: BusRequest | None = None):
    session = get_session()
    bus = req.bus_serial if req else "auto"
    try:
        return await session.close_gripper(bus)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/torque/enable")
async def enable_torque(req: BusRequest | None = None):
    session = get_session()
    bus = req.bus_serial if req else "auto"
    try:
        return await session.enable_arm_torque(bus)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/torque/disable")
async def disable_torque(req: BusRequest | None = None):
    session = get_session()
    bus = req.bus_serial if req else "auto"
    try:
        return await session.disable_arm_torque(bus)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/emergency-stop")
async def emergency_stop(req: BusRequest | None = None):
    session = get_session()
    bus = req.bus_serial if req else "auto"
    try:
        return await session.emergency_stop(bus)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/pick")
async def pick_object(req: PickRequest):
    session = get_session()
    try:
        return await session.pick_object(
            req.approach_positions, req.grasp_positions, req.lift_positions, req.bus_serial,
        )
    except ValueError as exc:
        return _error(exc, 400)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/place")
async def place_object(req: PlaceRequest):
    session = get_session()
    try:
        return await session.place_object(
            req.place_positions, req.retreat_positions, req.bus_serial,
        )
    except ValueError as exc:
        return _error(exc, 400)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/vla/load")
async def vla_load(req: VLALoadRequest):
    bridge = get_vla_bridge()
    try:
        return await asyncio.to_thread(bridge.load, req.checkpoint_path, req.device or None)
    except FileNotFoundError as exc:
        return _error(exc, 404)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/vla/step")
async def vla_step(req: VLAStepRequest):
    bridge = get_vla_bridge()
    session = get_session()
    try:
        return await bridge.run_steps(
            session, req.task, req.n_steps, req.bus_serial, max_delta_ticks=req.max_delta_ticks,
        )
    except RuntimeError as exc:
        return _error(exc, 400)
    except TimeoutError as exc:
        return _error(exc, 504)
    except Exception as exc:
        return _error(exc, 500)


# ── N8N Integration ────────────────────────────────────────────────────────

_n8n_alerts: list[dict[str, Any]] = []
MAX_ALERTS = 100


@app.post("/api/n8n/alert")
async def n8n_alert(req: N8NAlertRequest):
    alert = req.model_dump()
    if not alert["timestamp"]:
        from datetime import datetime, timezone
        alert["timestamp"] = datetime.now(timezone.utc).isoformat()
    _n8n_alerts.append(alert)
    if len(_n8n_alerts) > MAX_ALERTS:
        _n8n_alerts.pop(0)
    logger.info("N8N alert [%s/%s]: %s", req.severity, req.alert_type, req.message)
    return {"status": "received", "total_alerts": len(_n8n_alerts)}


@app.get("/api/n8n/alerts")
async def n8n_alerts(limit: int = Query(20, ge=1, le=100)):
    return {"alerts": _n8n_alerts[-limit:], "total": len(_n8n_alerts)}


# ── WebSocket ───────────────────────────────────────────────────────────────


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    await websocket.accept()
    session = get_session()
    try:
        await session.ensure_connected()
        await session.wait_for_inference(timeout_s=15.0)
    except Exception as exc:
        await websocket.send_json({"error": str(exc)})
        await websocket.close()
        return

    try:
        while True:
            try:
                state: dict[str, Any] = {"arm": session.get_arm_state()}
            except Exception as exc:
                state = {"arm_error": str(exc)}

            try:
                state["camera"] = session.get_camera_image()
            except Exception:
                pass

            state["connection"] = session.connection_info()
            await websocket.send_json(state)
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
