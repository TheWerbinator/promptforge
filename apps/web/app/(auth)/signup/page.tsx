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
  password: z.string().min(8, "At least 8 characters"),
  displayName: z.string().max(120).optional(),
  orgName: z.string().max(120).optional(),
});
type Values = z.infer<typeof schema>;

export default function SignupPage() {
  const { signup } = useAuth();
  const router = useRouter();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  const onSubmit = handleSubmit(async (values) => {
    setFormError(null);
    const res = await signup(values);
    if (!res.ok) {
      setFormError(res.error ?? "Signup failed");
      return;
    }
    router.push("/dashboard");
    router.refresh();
  });

  return (
    <main className="flex flex-1 items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <h1 className="mb-6 text-2xl font-semibold">Create your workspace</h1>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <Field label="Email" error={errors.email?.message}>
            <input type="email" autoComplete="email" className={inputCls} {...register("email")} />
          </Field>
          <Field label="Password" error={errors.password?.message}>
            <input
              type="password"
              autoComplete="new-password"
              className={inputCls}
              {...register("password")}
            />
          </Field>
          <Field label="Display name (optional)" error={errors.displayName?.message}>
            <input type="text" autoComplete="name" className={inputCls} {...register("displayName")} />
          </Field>
          <Field label="Workspace name (optional)" error={errors.orgName?.message}>
            <input type="text" className={inputCls} {...register("orgName")} />
          </Field>
          {formError && <p className="text-sm text-red-400">{formError}</p>}
          <button type="submit" disabled={isSubmitting} className={btnCls}>
            {isSubmitting ? "Creating…" : "Sign up"}
          </button>
        </form>
        <p className="mt-4 text-sm text-neutral-400">
          Already have an account?{" "}
          <Link href="/login" className="text-neutral-200 underline underline-offset-4">
            Log in
          </Link>
        </p>
      </div>
    </main>
  );
}
