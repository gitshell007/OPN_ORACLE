import { dossierFixtures, signalFixtures } from "./fixtures";
import { readAddedDossiers, readSettings, readSignalActions, STORAGE, writeAddedDossiers, writeLocal, writeSignalActions } from "./storage";
import type { CreateDossierInput, DossierFilters, OracleRepository, SignalAction, StrategicDossier, UserSettings } from "./types";

const delay = <T,>(value:T,ms=280)=>new Promise<T>(resolve=>setTimeout(()=>resolve(value),ms));

export class MockOracleRepository implements OracleRepository {
  async listDossiers(filters:DossierFilters={}) {
    const all=[...readAddedDossiers(),...dossierFixtures];
    const q=filters.query?.toLocaleLowerCase("es") ?? "";
    return delay(all.filter(d=>(!q||`${d.title} ${d.objective}`.toLowerCase().includes(q))&&(!filters.status||filters.status==="all"||d.status===filters.status)&&(!filters.type||filters.type==="all"||d.type===filters.type)&&(!filters.risk||filters.risk==="all"||d.riskLevel===filters.risk)));
  }
  async getDossier(id:string){ return delay([...readAddedDossiers(),...dossierFixtures].find(d=>d.id===id)??null); }
  async listSignals(dossierId?:string){
    const actions=readSignalActions();
    const signals=signalFixtures.map(s=>({...s,status:actions.find(a=>a.signalId===s.id)?.status??s.status}));
    return delay(dossierId?signals.filter(s=>s.dossierId===dossierId):signals);
  }
  async createDossier(input:CreateDossierInput){
    const added=readAddedDossiers();
    const dossier:StrategicDossier={id:`custom-${Date.now()}`,title:input.title,type:input.type,typeLabel:input.type.replaceAll("_"," "),status:"active",owner:input.owner,healthScore:70,opportunityScore:65,riskScore:35,riskLevel:"low",newSignals:0,nextMilestone:input.monitorEnabled?"Primera sincronización":"Definir monitor",nextMilestoneDate:"2026-07-17",updatedAt:"2026-07-10T09:30:00+02:00",geography:input.geography.split(",").map(v=>v.trim()).filter(Boolean),sectors:input.sectors.split(",").map(v=>v.trim()).filter(Boolean),objective:input.objective,livingSummary:"Expediente creado. Oracle espera la primera revisión del equipo para consolidar hipótesis y próximos pasos.",opportunities:[],risks:[],actors:[],timeline:[{id:"created",date:"2026-07-10",type:"decision",title:"Expediente creado",detail:"Pendiente de validación inicial."}]};
    writeAddedDossiers([dossier,...added]); return delay(dossier);
  }
  async updateSignal(action:SignalAction){ const actions=readSignalActions().filter(a=>a.signalId!==action.signalId);writeSignalActions([action,...actions]);const signal=signalFixtures.find(s=>s.id===action.signalId);if(!signal)throw new Error("Señal no encontrada");return delay({...signal,status:action.status}); }
  async updateUserSettings(input:UserSettings){ writeLocal(STORAGE.settings,input); return delay(input,160); }
  getUserSettings(){ return readSettings(); }
}

export const oracleRepository = new MockOracleRepository();
