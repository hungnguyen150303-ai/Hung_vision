# app/mqtt/client.py
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Callable, Dict, Optional, Any

import paho.mqtt.client as mqtt

log = logging.getLogger("vision.mqtt")


def _parse_payload(payload_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Trả về dict JSON từ MQTT payload.
    - Chuẩn hoá CRLF/BOM/NUL
    - Tự xử lý trường hợp double-encoded JSON (string chứa JSON)
    """
    s = payload_bytes.decode("utf-8", "ignore")
    # normalize
    s = s.replace("\r\n", "\n").replace("\r", "\n").strip().lstrip("\ufeff").strip("\x00")

    # try 1
    try:
        data = json.loads(s)
    except Exception:
        # thử gỡ một lớp (khi payload là chuỗi JSON bên trong chuỗi)
        try:
            inner = json.loads(s)
            if isinstance(inner, str):
                data = json.loads(inner)
            else:
                raise
        except Exception as e:
            log.error("MQTT JSON decode failed: %s; payload=%r", e, s)
            return None

    # nếu vẫn là string -> thử thêm 1 lần
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            log.error("MQTT JSON double-encoded; cannot parse: %r", data)
            return None

    if not isinstance(data, dict):
        log.error("MQTT payload must be a JSON object; got %s", type(data).__name__)
        return None

    return data


class _MqttBus:
    """
    MQTT bus duy nhất cho ứng dụng.
    - Chỉ subscribe 1 topic điều khiển: method_topic (mặc định 'vision/method')
    - Publish kết quả lên result_topic (mặc định 'vision/result')
    - Callback on_method: (type:str, method:str, overrides:dict) -> dict
    - get_status: () -> dict (tuỳ chọn)
    """

    def __init__(self) -> None:
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._pub_lock = threading.RLock()

        # cấu hình/ctx
        self.host = "127.0.0.1"
        self.port = 1883
        self.keepalive = 60
        self.username: Optional[str] = None
        self.password: Optional[str] = None
        self.client_id = f"vision-svc-{os.getpid()}"

        self.method_topic = "vision/method"
        self.result_topic = "vision/result"
        self._on_method: Optional[Callable[[str, str, Dict[str, Any]], Dict[str, Any]]] = None
        self._get_status: Optional[Callable[[], Dict[str, Any]]] = None

    # ---------- Public API ----------
    def start(
        self,
        settings,
        *,
        on_method: Callable[[str, str, Dict[str, Any]], Dict[str, Any]],
        get_status: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        # lấy cấu hình từ settings (nếu có)
        self.host = getattr(settings, "MQTT_HOST", self.host)
        self.port = int(getattr(settings, "MQTT_PORT", self.port))
        self.keepalive = int(getattr(settings, "MQTT_KEEPALIVE", self.keepalive))
        self.username = getattr(settings, "MQTT_USERNAME", None) or None
        self.password = getattr(settings, "MQTT_PASSWORD", None) or None
        self.client_id = getattr(settings, "MQTT_CLIENT_ID", self.client_id)

        self.method_topic = getattr(settings, "MQTT_METHOD_TOPIC", self.method_topic)
        self.result_topic = getattr(settings, "MQTT_RESULT_TOPIC", self.result_topic)

        self._on_method = on_method
        self._get_status = get_status

        # init client
        self._client = mqtt.Client(client_id=self.client_id, clean_session=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        if self.username and self.password:
            self._client.username_pw_set(self.username, self.password)

        # set userdata cho on_message
        self._client.user_data_set(
            {
                "method_topic": self.method_topic,
                "on_method": self._on_method,
                "get_status": self._get_status,
            }
        )

        # callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # connect & loop
        self._client.connect(self.host, self.port, keepalive=self.keepalive)
        self._client.loop_start()

    def stop(self) -> None:
        try:
            if self._client is None:
                return
            self._client.loop_stop()
            try:
                self._client.disconnect()
            except Exception:
                pass
        finally:
            self._client = None
            self._connected = False

    def publish_result(self, obj: Dict[str, Any], qos: int = 1, retain: bool = False) -> None:
        """
        Publish JSON lên result_topic (mặc định 'vision/result').
        """
        if self._client is None:
            return
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        with self._pub_lock:
            try:
                self._client.publish(self.result_topic, payload, qos=qos, retain=retain)
            except Exception as e:
                log.error("Publish result failed: %s", e)

    # ---------- Callbacks ----------
    def _on_connect(self, client: mqtt.Client, userdata: dict, flags, rc: int):
        self._connected = (rc == 0)
        if rc == 0:
            log.info("MQTT connected. Subscribing to %s", userdata["method_topic"])
            # chỉ subscribe method topic duy nhất
            client.subscribe(userdata["method_topic"], qos=1)
            log.info("MQTT method topic subscribed: %s", userdata["method_topic"])
        else:
            log.error("MQTT connect failed rc=%s", rc)

    def _on_disconnect(self, client: mqtt.Client, userdata: dict, rc: int):
        self._connected = False
        if rc != 0:
            log.warning("MQTT disconnected unexpectedly rc=%s (auto-reconnect enabled)", rc)

    def _on_message(self, client: mqtt.Client, userdata: dict, msg):
        try:
            topic = msg.topic
            if topic != userdata["method_topic"]:
                # Bỏ qua các topic khác (nếu broker forward)
                log.debug("Ignore topic=%s", topic)
                return

            data = _parse_payload(msg.payload)
            if data is None:
                return  # đã log lỗi ở _parse_payload

            # { "type": "...", "payload": { "method": "...", "overrides": {...} } }
            mtype = (data.get("type") or "").lower().strip()
            payload = data.get("payload") or {}
            method = (payload.get("method") or "").lower().strip()
            overrides = payload.get("overrides") or {}

            if not mtype or not method:
                log.error("MQTT method message missing 'type' or 'method': %r", data)
                return

            # dispatch ra lifecycle callback
            on_method = userdata.get("on_method")
            if callable(on_method):
                try:
                    res = on_method(mtype, method, overrides)
                except Exception as e:
                    log.exception("Dispatch error: %s", e)
                    return

                # log gọn kết quả
                ok = False
                running = None
                if isinstance(res, dict):
                    ok = bool(res.get("ok", False))
                    running = res.get("running", None)
                log.info("method=%s type=%s -> ok=%s running=%s", method, mtype, ok, running)
            else:
                log.error("on_method callback is not set")

        except Exception:
            log.exception("Unhandled MQTT on_message error")


# Singleton bus mà các service dùng: mqtt_bus.publish_result({...})
mqtt_bus = _MqttBus()
