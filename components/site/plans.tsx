import Link from "next/link";
import { ArrowRight } from "./icons";
import { PLANS, type Plan } from "@/lib/plans";

/** The plan cards, shared by /pricing and Billing. */
export function PlanCards({ current }: { current?: Plan["id"] }) {
  return (
    <ul className="ci-plans">
      {PLANS.map((plan) => (
        <li
          key={plan.id}
          className="ci-plan"
          data-featured={plan.featured ? "" : undefined}
        >
          <div className="ci-plan-head">
            <h2 id={`plan-${plan.id}`}>{plan.name}</h2>
            {current === plan.id && (
              <span className="ci-plan-tag">Current</span>
            )}
          </div>
          <p className="ci-plan-price">
            <strong data-word={/\d/.test(plan.price) ? undefined : ""}>
              {plan.price}
            </strong>
            <span>{plan.cadence}</span>
          </p>
          <p className="ci-plan-summary">{plan.summary}</p>
          <ul className="ci-plan-features">
            {plan.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          {current !== plan.id && (
            <Link
              className={plan.featured ? "ci-btn" : "ci-btn-quiet"}
              href={plan.cta.href}
            >
              {plan.cta.label} <ArrowRight />
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}
