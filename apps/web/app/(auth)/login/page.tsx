"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { btnCls, Field, inputCls } from "@/components/form";
import { useAuth } from "@/lib/auth-context";

const schema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    const res = await login(values.email, values.password);
    if (!res.ok) {
      setFormError(res.error ?? "Login failed");
      return;
    }
    router.push("/dashboard");
    router.refresh();
  });

  return (
    <main className="flex flex-1 items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-2xl font-semibold">Log in</h1>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Field label="Email" error={errors.email?.message}>
            <input type="email" autoComplete="email" className={inputCls} {...register("email")} />
          </Field>
          <Field label="Password" error={errors.password?.message}>
            <input
              type="password"
              autoComplete="current-password"
              className={inputCls}
              {...register("password")}
            />
          </Field>
          {formError && <p className="text-sm text-red-400">{formError}</p>}
          <button type="submit" disabled={isSubmitting} className={btnCls}>
            {isSubmitting ? "Logging in…" : "Log in"}
          </button>
        </form>
        <p className="mt-4 text-sm text-neutral-400">
          No account?{" "}
          <Link href="/signup" className="text-neutral-200 underline underline-offset-4">
            Sign up
          </Link>
        </p>
      </div>
    </main>
  );
}
