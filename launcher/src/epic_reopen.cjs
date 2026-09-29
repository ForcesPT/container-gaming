'use strict';

// A tray-hidden official Epic window may outlive the picker-owned controller.
// Keep concurrent selections on one restore request. Never hide the picker
// until the compositor confirms a window and focus actually succeeds.
const pending = new WeakMap();

function reopenManagedEpic({ owner, isCurrent, isVisible, requestRestore, focus,
  hide, notify, wait = ms => new Promise(resolve => setTimeout(resolve, ms)),
  attempts = 60 }) {
  if (pending.has(owner)) return pending.get(owner);
  const operation = (async () => {
    try {
      if (!isCurrent() || !requestRestore()) {
        return { ok: false, error: 'Epic could not be reopened; select Epic again after it finishes closing' };
      }
      for (let attempt = 0; attempt < attempts; attempt++) {
        if (!isCurrent()) return { ok: false, error: 'Epic finished closing; select Epic again to launch' };
        if (isVisible()) {
          if (!focus()) return { ok: false, error: 'Epic opened but its window could not be focused' };
          hide();
          notify();
          return { ok: true, resumed: true, storeId: 'epic', pid: owner.pid };
        }
        await wait(500);
      }
      return { ok: false, error: 'Epic is still running without a visible window. Try again when its update or game has finished.' };
    } catch {
      return { ok: false, error: 'Epic could not be reopened. Please try again.' };
    }
  })();
  pending.set(owner, operation);
  operation.finally(() => pending.delete(owner));
  return operation;
}

module.exports = { reopenManagedEpic };
