const STATUS_LABELS: Record<string, string> = {
  draft: "Borrador",
  active: "Activo",
  paused: "Pausado",
  archived: "Archivado",
  new: "Nueva",
  reviewed: "Revisada",
  promoted: "Promovida",
  dismissed: "Descartada",
  identified: "Identificada",
  qualified: "Cualificada",
  pursuing: "En curso",
  won: "Ganada",
  lost: "Perdida",
  open: "Abierto",
  monitoring: "En vigilancia",
  mitigated: "Mitigado",
  accepted: "Aceptado",
  closed: "Cerrado",
  planned: "Planificada",
  completed: "Completada",
  cancelled: "Cancelada",
  in_progress: "En curso",
  blocked: "Bloqueada",
  done: "Completada",
  proposed: "Propuesta",
  approved: "Aprobada",
  rejected: "Rechazada",
  queued: "En cola",
  running: "En ejecución",
  retrying: "Reintentando",
  succeeded: "Correcto",
  failed: "Fallido",
  ready: "Listo",
  processing: "Procesando",
  pending: "Pendiente",
  quarantined: "En cuarentena",
  invited: "Invitado",
  suspended: "Suspendido",
  revoked: "Revocado",
  disabled: "Desactivado",
  locked: "Bloqueado",
  configured: "Configurado",
  healthy: "Operativo",
  degraded: "Funcionamiento parcial",
  error: "Con incidencia",
  ok: "Operativo",
  success: "Correcto",
  clean: "Sin amenazas",
  infected: "Amenaza detectada",
  not_configured: "Sin antivirus configurado",
  uploaded: "Subido",
};

const JOB_TYPE_LABELS: Record<string, string> = {
  "maintenance.cleanup_tokens": "Limpieza de credenciales temporales",
  "maintenance.dispatch_due_jobs": "Activación de procesos programados",
  "maintenance.dispatch_queued_jobs": "Distribución de procesos pendientes",
  "maintenance.documents_retention": "Retención de documentos",
  "maintenance.expire_sessions": "Cierre de sesiones caducadas",
  "maintenance.recover_stale_jobs": "Recuperación de procesos interrumpidos",
  "maintenance.schedule_alert_evaluations": "Programación de alertas",
  "maintenance.signal_reconcile_inbox": "Conciliación de señales recibidas",
  "maintenance.signal_reconcile_outbox": "Conciliación de señales enviadas",
  "maintenance.weekly_digest": "Resumen semanal",
  "notifications.evaluate_alerts": "Evaluación de alertas",
  "notifications.send_digest": "Envío de resumen",
  "notifications.send_email": "Envío de correo",
  "notifications.send_notification": "Envío de notificación",
  "oracle.ai.actor_partnership": "Análisis de alianzas",
  "oracle.ai.entity_resolution": "Resolución de entidades",
  "oracle.ai.evidence_reviewer": "Revisión de evidencias",
  "oracle.ai.intake": "Análisis de entrada",
  "oracle.ai.meeting_briefing": "Preparación de reunión",
  "oracle.ai.memory_curator": "Consolidación de memoria estratégica",
  "oracle.ai.opportunity": "Análisis de oportunidades",
  "oracle.ai.report_writer": "Redacción de informe",
  "oracle.ai.risk": "Análisis de riesgos",
  "oracle.ai.signal_triage": "Clasificación de señales",
  "oracle.ai.weekly_change": "Análisis de cambios semanales",
  "oracle.document.process": "Procesamiento de documento",
  "oracle.export.generate": "Generación de exportación",
  "oracle.memory.refresh": "Actualización de memoria estratégica",
  "oracle.report.generate": "Generación de informe",
  "oracle.signal.dispatch_outbox": "Envío de señales",
  "oracle.signal.process_inbox": "Procesamiento de señales recibidas",
  "oracle.signal.sync_monitor": "Sincronización de monitor",
  "oracle.signal.triage": "Clasificación de señales",
};

const QUEUE_LABELS: Record<string, string> = {
  ai: "Inteligencia",
  default: "General",
  documents: "Documentos",
  maintenance: "Mantenimiento",
  notifications: "Notificaciones",
  signals: "Señales",
};

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrador",
  analyst: "Analista",
  auditor: "Auditor",
  editor: "Editor",
  owner: "Propietario",
  viewer: "Consulta",
};

const PLAN_LABELS: Record<string, string> = {
  enterprise: "Empresarial",
  professional: "Profesional",
  starter: "Inicial",
  trial: "Evaluación",
};

const DOSSIER_TYPE_LABELS: Record<string, string> = {
  project: "Proyecto",
  strategic_account: "Cuenta estratégica",
  market: "Mercado",
  technology: "Tecnología",
  tender_or_grant: "Licitación o convocatoria",
  investment: "Inversión",
  partnership: "Alianza",
  product_launch: "Lanzamiento de producto",
  regulatory_affair: "Asunto regulatorio",
  risk_watch: "Seguimiento de riesgos",
  custom: "Otro",
};

const SIGNAL_TYPE_LABELS: Record<string, string> = {
  news: "Noticias y prensa",
  official_publication: "Publicación oficial",
  social_signal: "Redes sociales",
  company_signal: "Actividad de una organización",
  market_signal: "Cambios de mercado",
  regulatory_signal: "Cambios regulatorios",
  tender_or_grant: "Licitación o convocatoria",
  relationship_signal: "Relación entre actores",
  internal_document: "Documento interno",
  risk_signal: "Señal de riesgo",
  opportunity_signal: "Señal de oportunidad",
};

const ACTOR_TYPE_LABELS: Record<string, string> = {
  person: "Persona",
  organization: "Organización",
  company: "Empresa",
  institution: "Institución",
  public_body: "Organismo público",
  technology: "Tecnología",
  place: "Lugar",
  other: "Otro",
};

const SCORE_DETAIL_LABELS: Record<string, string> = {
  confidence: "Confianza",
  human_override: "Ajuste humano",
  normalized_execution_effort: "Esfuerzo de ejecución normalizado",
};

const AUDIT_ACTION_LABELS: Record<string, string> = {
  "actor.merged": "Actores unificados",
  "auth.password_reset.queued": "Recuperación de contraseña solicitada",
  "background_job.cancel_requested": "Cancelación de proceso solicitada",
  "background_job.cancelled": "Proceso cancelado",
  "background_job.failed": "Proceso fallido",
  "background_job.retry_requested": "Reintento de proceso solicitado",
  "background_job.succeeded": "Proceso completado",
  "briefing.created": "Documento preparatorio creado",
  "dossier.collaborator_removed": "Colaborador retirado del expediente",
  "dossier.collaborator_set": "Colaborador asignado al expediente",
  "dossier.created": "Expediente creado",
  "dossier.updated": "Expediente actualizado",
  "evidence.created": "Evidencia creada",
  "export.ready": "Exportación preparada",
  "export.requested": "Exportación solicitada",
  "feedback.created": "Valoración registrada",
  "integration.signal.create": "Conexión de Signal creada",
  "integration.signal.disable": "Conexión de Signal desactivada",
  "integration.signal.rotate": "Credencial de Signal renovada",
  "notification_preferences.updated": "Preferencias de notificación actualizadas",
  "platform.backup.manual_requested": "Copia manual solicitada",
  "platform.backup.restore_requested": "Recuperación de copia solicitada",
  "platform.bootstrap.superadmin": "Superadministrador preparado",
  "platform.tenant.created": "Organización creada",
  "platform.tenant_access.authorized": "Acceso administrativo autorizado",
  "report.published": "Informe publicado",
  "report.ready": "Informe preparado",
  "report.requested": "Informe solicitado",
  "signal.promoted": "Señal promovida",
  "signal.reviewed": "Señal revisada",
  "signal_monitor.created": "Monitor de señales creado",
  "tenant.invitation.reissued": "Invitación reenviada",
  "tenant.invitation.used": "Invitación aceptada",
  "tenant.member.invited": "Miembro invitado",
  "tenant.member.removed": "Miembro retirado",
  "tenant.member.roles_changed": "Roles del miembro actualizados",
  "tenant.member.status_changed": "Acceso del miembro actualizado",
};

export function productStatusLabel(status?: string | null): string {
  if (!status) return "—";
  return STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}

export function productJobTypeLabel(jobType?: string | null): string {
  if (!jobType) return "Proceso sin identificar";
  return JOB_TYPE_LABELS[jobType] ?? "Proceso interno de Oracle";
}

export function productQueueLabel(queue?: string | null): string {
  if (!queue) return "General";
  return QUEUE_LABELS[queue] ?? "General";
}

export function productRoleLabel(role?: string | null): string {
  if (!role) return "Sin rol asignado";
  return ROLE_LABELS[role] ?? "Rol personalizado";
}

export function productPlanLabel(plan?: string | null): string {
  if (!plan) return "Sin plan asignado";
  return PLAN_LABELS[plan] ?? "Plan personalizado";
}

export function productDossierTypeLabel(type?: string | null): string {
  if (!type) return "Expediente estratégico";
  return DOSSIER_TYPE_LABELS[type] ?? "Expediente estratégico";
}

export function productSignalTypeLabel(type?: string | null): string {
  if (!type) return "Tipo de fuente no indicado";
  return SIGNAL_TYPE_LABELS[type] ?? "Fuente externa";
}

export function productActorTypeLabel(type?: string | null): string {
  if (!type) return "Actor";
  return ACTOR_TYPE_LABELS[type] ?? "Actor";
}

export function productLinkedResourceLabel(type?: string | null): string {
  const labels: Record<string, string> = {
    opportunity: "oportunidad",
    opportunities: "oportunidad",
    risk: "riesgo",
    risks: "riesgo",
    signal: "señal",
    signals: "señal",
    meeting: "reunión",
    meetings: "reunión",
    decision: "decisión",
    document: "documento",
  };
  return labels[type ?? ""] ?? "elemento del expediente";
}

export function productResourceKindLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    high: "Prioridad alta",
    medium: "Prioridad media",
    low: "Prioridad baja",
    meeting: "Reunión",
    task: "Tarea",
    opportunity: "Oportunidad",
    risk: "Riesgo",
  };
  return labels[value ?? ""] ?? "Elemento del expediente";
}

export function productScoreDetailLabel(key: string): string | null {
  return SCORE_DETAIL_LABELS[key] ?? null;
}

export function productAuditActionLabel(action?: string | null): string {
  if (!action) return "Actividad registrada";
  return AUDIT_ACTION_LABELS[action] ?? "Actividad administrativa registrada";
}
