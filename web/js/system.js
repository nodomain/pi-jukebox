/**
 * System diagnostics: BT status polling, service actions.
 * @module system
 */

import {
  fetchBtStatus, fetchBtScan, fetchBtConnect,
  fetchBtDisconnect, serviceAction,
} from './api.js';
import { handleBtStatus } from './player.js';

/** Poll Bluetooth status (fallback for initial load). */
export async function pollBt() {
  try {
    handleBtStatus(await fetchBtStatus());
  } catch (e) {
    // Ignore
  }
}

/** Scan for Bluetooth devices and populate the list. */
export async function btScan() {
  const btn = document.getElementById('btn-scan');
  btn.disabled = true;
  btn.textContent = 'Scanning...';
  try {
    const d = await fetchBtScan();
    document.getElementById('bt-devices').innerHTML = d.devices.map(dev =>
      `<li><span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${dev.name}</span><button data-bt-mac="${dev.mac}" style="flex-shrink:0">Connect</button></li>`
    ).join('');
  } catch (e) {
    // Ignore
  }
  btn.disabled = false;
  btn.textContent = 'Scan';
}

/** Connect to a Bluetooth device by MAC. */
export async function btConnect(mac) {
  const d = await fetchBtConnect(mac);
  alert(d.success ? 'Connected!' : 'Failed: ' + d.result);
  pollBt();
}

/** Disconnect the currently connected Bluetooth device. */
export async function btDisconnect() {
  const d = await fetchBtStatus();
  if (d.mac) {
    await fetchBtDisconnect(d.mac);
  }
  pollBt();
}

/** Perform a service action (restart-snapclient, restart-bt, reboot). */
export async function svcAction(action) {
  await serviceAction(action);
  if (action === 'reboot') {
    document.body.innerHTML = '<h1 style="text-align:center;margin-top:40vh">Rebooting...</h1>';
  }
}

/** Initialize BT device list click delegation. */
export function initSystemEvents() {
  document.getElementById('bt-devices').addEventListener('click', function (e) {
    const btn = e.target.closest('[data-bt-mac]');
    if (btn) btConnect(btn.dataset.btMac);
  });
}
