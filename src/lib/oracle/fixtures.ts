import type { Actor, Signal, StrategicDossier, UserSettings } from "./types";

export const DEMO_NOW = new Date("2026-07-10T09:30:00+02:00");

const actors: Actor[] = [
  ["a1", "Agencia Arco", "institution", "Regulador", 92, 62], ["a2", "NovaBridge", "organisation", "Partner potencial", 81, 88],
  ["a3", "Colectivo Lumen", "organisation", "Prescriptor", 67, 74], ["a4", "Consejo Boreal", "institution", "Decisor", 90, 71],
  ["a5", "Vértice Labs", "organisation", "Competidor", 78, 28], ["a6", "Foro Trama", "organisation", "Canal", 58, 82],
  ["a7", "Marina Soler", "person", "Experta técnica", 71, 85], ["a8", "Tomás Vega", "person", "Decisor", 84, 68],
  ["a9", "Instituto Cénit", "institution", "Financiador", 87, 76], ["a10", "Atria Systems", "organisation", "Proveedor", 61, 79],
  ["a11", "Red Umbral", "organisation", "Aliado", 69, 91], ["a12", "Fundación Prisma", "institution", "Prescriptor", 73, 83],
].map(([id,name,kind,role,influence,alignment]) => ({ id, name, kind, role, influence, alignment } as Actor));

const base = [
  ["dach-2027", "Expansión DACH 2027", "market", "Mercado", 72, 88, 61, "high", 5, "Validar partner local", "2026-07-18"],
  ["aurora", "Planta Circular Aurora", "project", "Proyecto", 64, 74, 86, "critical", 3, "Mesa de permisos", "2026-07-14"],
  ["horizonte", "Licitación Horizonte Digital", "tender_or_grant", "Licitación", 79, 94, 58, "medium", 4, "Decisión go / no-go", "2026-07-12"],
  ["northstar", "Cuenta Estratégica Northstar", "strategic_account", "Cuenta estratégica", 76, 82, 49, "medium", 2, "Reunión de alineación", "2026-07-21"],
  ["helix", "Alianza Helix", "partnership", "Alianza", 83, 91, 37, "low", 1, "Term sheet preliminar", "2026-07-25"],
  ["nordico", "Entrada Mercado Nórdico", "market", "Mercado", 69, 78, 55, "medium", 2, "Seleccionar canal", "2026-07-29"],
  ["atlas", "Programa Atlas de Innovación", "project", "Programa", 88, 84, 31, "low", 1, "Comité de portfolio", "2026-08-03"],
  ["terra", "Observatorio Regulatorio Terra", "regulatory_affair", "Asunto regulatorio", 71, 63, 79, "high", 4, "Publicación de dictamen", "2026-07-16"],
] as const;

export const dossierFixtures: StrategicDossier[] = base.map((d, i) => ({
  id:d[0], title:d[1], type:d[2], typeLabel:d[3], status:i === 5 ? "paused" : "active", owner:i % 3 === 0 ? "Lucía Herrera" : i % 3 === 1 ? "Sergio Navas" : "Marta Cid",
  healthScore:d[4], opportunityScore:d[5], riskScore:d[6], riskLevel:d[7], newSignals:d[8], nextMilestone:d[9], nextMilestoneDate:d[10],
  updatedAt:`2026-07-${String(10 - (i % 5)).padStart(2,"0")}T0${8 + (i % 2)}:15:00+02:00`, geography:i % 2 ? ["España", "UE"] : ["Alemania", "Austria", "Suiza"],
  sectors:i % 3 === 0 ? ["Servicios avanzados"] : i % 3 === 1 ? ["Industria circular"] : ["Tecnología pública"],
  objective:i === 0 ? "Validar y ejecutar una entrada ordenada en la región DACH antes del segundo trimestre de 2027." : `Asegurar el siguiente hito estratégico de ${d[1]} con evidencia suficiente para decidir.`,
  livingSummary:i === 0 ? "El encaje de mercado se mantiene alto y ha aparecido una vía de financiación relevante. La principal incertidumbre es la dependencia de un partner local antes del cierre regulatorio." : `${d[1]} avanza con una oportunidad accionable y un punto de vigilancia que requiere decisión durante las próximas dos semanas.`,
  opportunities:[{id:`o${i+1}`,title:i===0?"Programa de entrada para empresas innovadoras":`Acelerador de ${d[1]}`,score:d[5],deadline:d[10],action:"Validar requisitos y asignar responsable",status:i%2?"candidate":"qualified"}],
  risks:[{id:`r${i+1}`,title:i===1?"Retraso en permisos ambientales":"Dependencia de validación externa",score:d[6],level:d[7],mitigation:"Preparar alternativa y confirmar responsables",status:d[7]==="low"?"accepted":"watch"}],
  actors:actors.slice(i % 6, (i % 6) + 4),
  timeline:[
    {id:`t${i}-1`,date:"2026-07-10",type:"signal",title:"Nueva señal priorizada",detail:"La revisión automática identifica impacto directo en el próximo hito."},
    {id:`t${i}-2`,date:"2026-07-08",type:"decision",title:"Hipótesis validada",detail:"El equipo mantiene la estrategia y solicita evidencia adicional."},
    {id:`t${i}-3`,date:"2026-07-04",type:"meeting",title:"Reunión de seguimiento",detail:"Se acordaron dos acciones y una fecha de decisión."},
  ],
}));

const signalTitles = [
  "Nueva línea de financiación para expansión regional", "Consulta pública sobre acceso al mercado", "NovaBridge anuncia una alianza de distribución",
  "Cambio en el calendario de autorización", "Vértice Labs refuerza su equipo regional", "Publicación técnica valida el enfoque operativo",
  "Convocatoria Horizonte abre fase de propuestas", "Actualización del marco de contratación pública", "Señal social anticipa cambios en el canal",
  "Informe de mercado revisa la previsión de demanda", "Documento interno actualiza la tesis de entrada", "Incidencia territorial exige plan alternativo",
  "Programa Cénit amplía presupuesto disponible", "Nuevo acuerdo de interoperabilidad", "Cambio directivo en actor clave",
  "Boletín regional aclara requisitos de elegibilidad", "Competidor anuncia piloto de alcance limitado", "Acta interna confirma decisión de inversión",
  "Red Umbral propone mesa de trabajo", "Observatorio publica criterio interpretativo",
];
const signalTypes = ["tender_or_grant","regulatory_signal","company_signal","risk_signal","company_signal","news","tender_or_grant","regulatory_signal","social_signal","market_signal","internal_document","risk_signal","opportunity_signal"] as const;

export const signalFixtures: Signal[] = signalTitles.map((title, i) => ({
  id:`s${i+1}`, dossierId:base[i % base.length][0], title, summary:`La señal aporta información verificable sobre ${base[i % base.length][1]} y modifica una hipótesis de trabajo activa.`,
  sourceType:signalTypes[i % signalTypes.length], sourceName:["Boletín Arco", "Monitor Avanza", "Archivo interno", "Observatorio Cénit"][i%4],
  publishedAt:`2026-07-${String(10 - (i % 7)).padStart(2,"0")}T0${8 + (i % 2)}:00:00+02:00`, relevance:96-(i*7%35), novelty:88-(i*5%31), confidence:91-(i*3%24), credibility:94-(i*4%19),
  status:i<7?"new":i%5===0?"promoted":i%4===0?"dismissed":"reviewed", whyItMatters:i===0?"Reduce el coste de entrada y adelanta la decisión sobre el partner local.":"Puede alterar el próximo hito, la prioridad o el plan de acción del expediente.",
  evidence:[{id:`ev${i}-1`,label:"Fragmento verificado",source:["Boletín Arco", "Monitor Avanza"][i%2],excerpt:"La publicación fija un nuevo requisito y una ventana de actuación concreta."},{id:`ev${i}-2`,label:"Contraste documental",source:"Archivo interno",excerpt:"La hipótesis de trabajo identifica este cambio como condición de avance."}],
  actors:[actors[i%actors.length].name,actors[(i+2)%actors.length].name],
}));

export const defaultSettings: UserSettings = { name:"Lucía Herrera",role:"Directora de Estrategia",email:"lucia.herrera@asterion.example",language:"Español",timezone:"Europe/Madrid",dateFormat:"DD/MM/AAAA",landing:"portfolio",density:"balanced",reducedMotion:false,showScoreExplanations:true,relevanceThreshold:70,digest:"daily",notifications:true,navigationCompact:false };

export const recentChanges = [
  {kind:"Oportunidad",title:"Financiación DACH supera el umbral de encaje",detail:"Confianza 86% · hace 34 min"},
  {kind:"Riesgo",title:"Permisos de Planta Aurora cambian de fecha",detail:"Impacto alto · hace 1 h"},
  {kind:"Actor",title:"NovaBridge entra en una alianza relevante",detail:"Expansión DACH · hace 2 h"},
  {kind:"Decisión",title:"Horizonte Digital requiere go / no-go",detail:"Vence el 12 jul"},
  {kind:"Reunión",title:"Northstar confirma mesa de alineación",detail:"21 jul · 10:30"},
];
