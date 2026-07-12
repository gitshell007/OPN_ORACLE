import type { DossierType, RiskLevel, SignalType } from "./types";
export const formatDate=(value:string,withTime=false)=>new Intl.DateTimeFormat("es-ES",withTime?{day:"2-digit",month:"short",hour:"2-digit",minute:"2-digit"}:{day:"2-digit",month:"short",year:"numeric"}).format(new Date(value));
export const riskLabel:Record<RiskLevel,string>={low:"Bajo",medium:"Medio",high:"Alto",critical:"Crítico"};
export const typeLabels:Record<DossierType,string>={project:"Proyecto",strategic_account:"Cuenta estratégica",market:"Mercado",technology:"Tecnología",tender_or_grant:"Convocatoria",investment:"Inversión",partnership:"Alianza",regulatory_affair:"Asunto regulatorio",custom:"Personalizado"};
export const signalTypeLabel:Record<SignalType,string>={tender_or_grant:"Convocatoria",regulatory_signal:"Regulación",company_signal:"Empresa",market_signal:"Mercado",social_signal:"Social",news:"Prensa",internal_document:"Documento interno",risk_signal:"Riesgo",opportunity_signal:"Oportunidad"};
