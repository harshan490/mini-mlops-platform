import clsx from "clsx";
import type { ReactNode } from "react";
import { CountUp, Eyebrow } from "@/lib/motion";
import { Delta } from "./primitives";
import { IconTile, Sparkline } from "./viz";

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  sub2,
  quote,
  right,
  className,
  titleClass,
}: {
  eyebrow: string;
  title: ReactNode;
  subtitle?: ReactNode;
  sub2?: ReactNode;
  quote?: [string, string];
  right?: ReactNode;
  className?: string;
  titleClass?: string;
}) {
  return (
    <div className={clsx("flex items-start justify-between gap-6", className)}>
      <div className="relative min-w-0 shrink-0 pl-5 before:absolute before:bottom-2 before:left-0 before:top-1 before:w-px before:bg-gradient-to-b before:from-transparent before:via-line/40 before:to-transparent">
        <Eyebrow text={eyebrow} className="mb-2" />
        <h1 data-intro="title" className={clsx("hero-title pb-1 text-[clamp(40px,4.3vw,68px)]", titleClass)}>
          {title}
        </h1>
        {subtitle && (
          <p data-intro="subtitle" className="mt-1 text-[clamp(14px,1.2vw,18px)] tracking-wide text-ink/90">
            {subtitle}
          </p>
        )}
        {sub2 && (
          <p data-intro="subtitle" className="mt-1 text-[13.5px] tracking-wide text-muted">
            {sub2}
          </p>
        )}
      </div>
      {right}
      {quote && (
        <div data-intro="quote" className="quote hidden shrink-0 pt-6 xl:block">
          <div>&ldquo;{quote[0]}</div>
          <div>{quote[1]}&rdquo;</div>
          <div className="ml-auto mt-3 h-px w-12 bg-ink/40" />
        </div>
      )}
    </div>
  );
}

export function StatCard({
  icon,
  color,
  label,
  value,
  decimals = 0,
  format,
  suffix,
  delta,
  deltaSuffix = "",
  deltaDigits = 0,
  invert,
  spark,
  className,
  onClick,
}: {
  icon: ReactNode;
  color: string;
  label: string;
  value: number | null | undefined;
  decimals?: number;
  format?: (v: number) => string;
  suffix?: string;
  delta?: number | null;
  deltaSuffix?: string;
  deltaDigits?: number;
  invert?: boolean;
  spark?: (number | null)[];
  className?: string;
  onClick?: () => void;
}) {
  return (
    <div
      data-intro="stat"
      onClick={onClick}
      className={clsx("glass glass-hover relative flex min-w-0 items-center gap-3.5 overflow-hidden px-4 py-3.5", onClick && "cursor-pointer", className)}
    >
      <IconTile color={color}>{icon}</IconTile>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] text-ink/85">{label}</div>
        <div className="flex items-baseline gap-2.5">
          <span className="text-[clamp(20px,1.7vw,27px)] font-semibold tabular-nums tracking-tight">
            <CountUp value={value} decimals={decimals} format={format} suffix={suffix} />
          </span>
          <Delta value={delta} suffix={deltaSuffix} digits={deltaDigits} invert={invert} />
        </div>
      </div>
      {spark && spark.length > 1 && (
        <Sparkline data={spark} color={color} width={86} height={30} className="absolute bottom-2 right-3 opacity-90" />
      )}
    </div>
  );
}
