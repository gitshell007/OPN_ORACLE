import type { SignalAction, StrategicDossier, UserSettings } from "./types";
import { defaultSettings } from "./fixtures";

export const STORAGE = { settings:"opn-oracle-prototype:v1:settings", dossiers:"opn-oracle-prototype:v1:dossiers", signals:"opn-oracle-prototype:v1:signal-actions" } as const;
let tenantScope = "showcase";
export function setStorageTenant(tenantId: string | null){ tenantScope = tenantId ?? "platform"; }
function tenantKey(key: string){ return `${key}:tenant:${tenantScope}`; }

export function readLocal<T>(key:string, fallback:T):T {
  if (typeof window === "undefined") return fallback;
  try { const value=window.localStorage.getItem(key); return value ? JSON.parse(value) as T : fallback; } catch { return fallback; }
}
export function writeLocal<T>(key:string,value:T){ if(typeof window!=="undefined") window.localStorage.setItem(key,JSON.stringify(value)); }
export function readSettings(){ return readLocal<UserSettings>(STORAGE.settings,defaultSettings); }
export function readAddedDossiers(){ return readLocal<StrategicDossier[]>(tenantKey(STORAGE.dossiers),[]); }
export function writeAddedDossiers(value: StrategicDossier[]){ writeLocal(tenantKey(STORAGE.dossiers), value); }
export function readSignalActions(){ return readLocal<SignalAction[]>(tenantKey(STORAGE.signals),[]); }
export function writeSignalActions(value: SignalAction[]){ writeLocal(tenantKey(STORAGE.signals), value); }
export function resetDemoState(){ if(typeof window!=="undefined"){ Object.keys(window.localStorage).filter(key=>key.startsWith("opn-oracle-prototype:v1:")).forEach(key=>window.localStorage.removeItem(key)); window.dispatchEvent(new Event("oracle:reset")); } }
