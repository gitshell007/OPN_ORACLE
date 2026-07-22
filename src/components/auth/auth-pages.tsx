"use client";

import { ApiError, api } from "@oracle/api-client";
import { Eye, EyeOff, LockKeyhole, Mail } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useState } from "react";
import { authenticatedLanding } from "@/lib/auth/safe-next";
import { useAuth } from "./auth-provider";

function AuthFrame({
  eyebrow,
  title,
  copy,
  children,
}: {
  eyebrow: string;
  title: string;
  copy: string;
  children: React.ReactNode;
}) {
  return (
    <main className="auth-page">
      <section className="auth-brand-panel" aria-label="OPN Oracle">
        <div className="auth-brand">
          <Image
            src="/brand/opn-symbol-white.svg"
            alt=""
            width={32}
            height={34}
            priority
          />
          <strong><b>OPN</b> <em>Oracle</em></strong>
        </div>
        <div>
          <p>INTELIGENCIA ESTRATÉGICA</p>
          <h2>Señales convertidas en decisiones trazables.</h2>
          <ul>
            <li>Evidencia y confianza visibles</li>
            <li>Aislamiento seguro por organización</li>
            <li>Orientación ofensiva y operativa</li>
          </ul>
        </div>
        <small>Acceso corporativo protegido</small>
      </section>
      <section className="auth-form-panel">
        <div className="auth-card">
          <p className="auth-eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="auth-intro">{copy}</p>
          {children}
        </div>
      </section>
    </main>
  );
}

function PasswordField({
  value,
  onChange,
  label = "Contraseña",
  autoComplete = "current-password",
}: {
  value: string;
  onChange(value: string): void;
  label?: string;
  autoComplete?: string;
}) {
  const [shown, setShown] = useState(false);
  return (
    <label className="auth-field">
      <span>{label}</span>
      <div>
        <LockKeyhole size={18} />
        <input
          type={shown ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          required
        />
        <button
          type="button"
          onClick={() => setShown((value) => !value)}
          aria-label={shown ? "Ocultar contraseña" : "Mostrar contraseña"}
        >
          {shown ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div>
    </label>
  );
}

function ProblemAlert({ error }: { error: ApiError | null }) {
  if (!error) return null;
  return (
    <div className="auth-alert" role="alert">
      <strong>No se pudo completar la solicitud</strong>
      <span>
        {error.status === 429
          ? `Demasiados intentos. Vuelve a probar${error.retryAfter ? ` en ${error.retryAfter} segundos` : " más tarde"}.`
          : error.message}
      </span>
    </div>
  );
}

export function LoginPage() {
  const auth = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [memberships, setMemberships] = useState<
    { tenant_id: string; tenant_name: string; tenant_slug: string }[]
  >([]);
  const [tenantId, setTenantId] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const identity = await auth.login(email, password, tenantId || undefined);
      router.replace(authenticatedLanding(search.get("next"), identity));
    } catch (reason) {
      if (
        reason instanceof ApiError &&
        reason.problem.code === "tenant_selection_required"
      ) {
        const errors = reason.problem.errors as
          | {
              memberships?: {
                tenant_id: string;
                tenant_name: string;
                tenant_slug: string;
              }[];
            }
          | undefined;
        setMemberships(errors?.memberships ?? []);
        setError(null);
      } else setError(reason instanceof ApiError ? reason : null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthFrame
      eyebrow="Acceso seguro"
      title="Bienvenido a Oracle"
      copy="Identifícate con tu cuenta corporativa para abrir el centro de operaciones."
    >
      <form onSubmit={submit} className="auth-form">
        <label className="auth-field">
          <span>Correo electrónico</span>
          <div>
            <Mail size={18} />
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </div>
        </label>
        <PasswordField value={password} onChange={setPassword} />
        {memberships.length > 0 && (
          <label className="auth-field">
            <span>Organización</span>
            <div>
              <select
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value)}
                required
                autoFocus
              >
                <option value="">Selecciona una organización</option>
                {memberships.map((item) => (
                  <option key={item.tenant_id} value={item.tenant_id}>
                    {item.tenant_name}
                  </option>
                ))}
              </select>
            </div>
          </label>
        )}
        <div className="auth-form-meta">
          <Link href="/forgot-password">¿Has olvidado la contraseña?</Link>
        </div>
        <ProblemAlert error={error} />
        <button className="auth-submit" disabled={busy}>
          {busy ? "Verificando…" : "Entrar en Oracle"}
        </button>
      </form>
      <p className="auth-footnote">
        El acceso y los cambios sensibles quedan registrados en la auditoría de
        seguridad.
      </p>
    </AuthFrame>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.auth.forgotPassword(email);
      setSent(true);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthFrame
      eyebrow="Recuperación"
      title="Recupera el acceso"
      copy="Te enviaremos instrucciones si la dirección corresponde a una cuenta activa."
    >
      {sent ? (
        <div className="auth-success" role="status">
          <strong>Solicitud recibida</strong>
          <p>
            Revisa tu correo. Por seguridad, mostramos el mismo resultado para
            todas las direcciones.
          </p>
          <Link href="/login">Volver al acceso</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="auth-form">
          <label className="auth-field">
            <span>Correo electrónico</span>
            <div>
              <Mail size={18} />
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                autoFocus
                required
              />
            </div>
          </label>
          <ProblemAlert error={error} />
          <button className="auth-submit" disabled={busy}>
            {busy ? "Enviando…" : "Enviar instrucciones"}
          </button>
          <Link className="auth-back" href="/login">
            Volver al acceso
          </Link>
        </form>
      )}
    </AuthFrame>
  );
}

export function NewPasswordPage({ mode }: { mode: "reset" | "invite" }) {
  const router = useRouter();
  const search = useSearchParams();
  const token = search.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError(
        new ApiError(422, {
          type: "about:blank",
          title: "Las contraseñas no coinciden",
          status: 422,
          detail: "Escribe la misma contraseña en ambos campos.",
          instance: "",
          code: "password_mismatch",
          request_id: "",
        }),
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "reset") await api.auth.resetPassword(token, password);
      else await api.auth.acceptInvitation(token, password);
      router.replace("/login?completed=1");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason : null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthFrame
      eyebrow={mode === "reset" ? "Nueva contraseña" : "Invitación"}
      title={
        mode === "reset"
          ? "Protege de nuevo tu cuenta"
          : "Activa tu acceso a Oracle"
      }
      copy="Usa una frase larga, única y fácil de recordar. El servidor verificará la política vigente."
    >
      <form onSubmit={submit} className="auth-form">
        {!token && (
          <div className="auth-alert" role="alert">
            El enlace no contiene un token válido.
          </div>
        )}
        <PasswordField
          value={password}
          onChange={setPassword}
          label="Nueva contraseña"
          autoComplete="new-password"
        />
        <PasswordField
          value={confirm}
          onChange={setConfirm}
          label="Repite la contraseña"
          autoComplete="new-password"
        />
        <p className="password-help">
          Evita contraseñas reutilizadas o triviales.
        </p>
        <ProblemAlert error={error} />
        <button className="auth-submit" disabled={busy || !token}>
          {busy
            ? "Guardando…"
            : mode === "reset"
              ? "Cambiar contraseña"
              : "Aceptar invitación"}
        </button>
      </form>
    </AuthFrame>
  );
}
