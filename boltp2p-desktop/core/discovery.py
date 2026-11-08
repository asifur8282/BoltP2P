"""
BoltP2P mDNS / Zeroconf LAN Auto-Discovery Engine
Publishes and listens for `_boltp2p._tcp.local.` services across the local subnet.
"""

import socket
import logging
from typing import Optional, Callable
from zeroconf import IPVersion, ServiceInfo, Zeroconf, ServiceBrowser, ServiceStateChange

SERVICE_TYPE = "_boltp2p._tcp.local."
logger = logging.getLogger("BoltP2P.Discovery")


def get_local_ip() -> str:
    """Resolve primary local network IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting to a public DNS IP without sending packets routes via LAN interface
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class DiscoveryManager:
    def __init__(self, device_name: str, port: int = 58241, on_peer_found: Optional[Callable] = None):
        self.device_name = device_name
        self.port = port
        self.on_peer_found = on_peer_found
        self.zeroconf: Optional[Zeroconf] = None
        self.service_info: Optional[ServiceInfo] = None
        self.browser: Optional[ServiceBrowser] = None

    def start(self) -> None:
        """Register the local BoltP2P daemon and browse for peers."""
        local_ip = get_local_ip()
        service_name = f"{self.device_name}.{SERVICE_TYPE}"

        properties = {
            "version": "1.0",
            "device": self.device_name,
            "os": "Windows 11",
            "port": str(self.port),
        }

        self.service_info = ServiceInfo(
            type_=SERVICE_TYPE,
            name=service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=self.port,
            properties=properties,
            server=f"{socket.gethostname().lower()}.local.",
        )

        try:
            self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self.zeroconf.register_service(self.service_info)
            logger.info("Broadcasting BoltP2P mDNS service on %s:%d", local_ip, self.port)

            # Browse for other BoltP2P peers
            self.browser = ServiceBrowser(
                self.zeroconf,
                [SERVICE_TYPE],
                handlers=[self._on_service_state_change]
            )
        except Exception as e:
            logger.warning("mDNS service registration warning: %s", e)

    def _on_service_state_change(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info and info.addresses:
                peer_ip = socket.inet_ntoa(info.addresses[0])
                peer_name = info.properties.get(b"device", b"Unknown").decode("utf-8", errors="ignore")
                local_ip = get_local_ip()
                if peer_ip != local_ip or info.port != self.port:
                    logger.info("Discovered BoltP2P peer: %s at %s:%d", peer_name, peer_ip, info.port)
                    if self.on_peer_found:
                        self.on_peer_found(peer_name, peer_ip, info.port)

    def stop(self) -> None:
        """Cleanly unregister mDNS service and close socket."""
        if self.zeroconf and self.service_info:
            try:
                self.zeroconf.unregister_service(self.service_info)
                self.zeroconf.close()
                logger.info("mDNS service stopped.")
            except Exception as e:
                logger.warning("Error stopping Zeroconf: %s", e)
        self.zeroconf = None
