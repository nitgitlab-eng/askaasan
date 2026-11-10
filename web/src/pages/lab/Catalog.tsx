import { useQuery } from "@tanstack/react-query";
import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/ui";
import { api } from "@/lib/api";

interface CatalogCard {
  id: number;
  title: string;
  description: string;
  level: string;
  language: string;
  cover_emoji: string;
  creator: string;
  lessons: number;
  learners: number;
  share_token: string;
}

export default function CatalogPage() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogCard[]>("/api/catalog/") });
  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-8">
      <header>
        <h1 className="font-display text-3xl font-extrabold">{t("catalog.title")}</h1>
        <p className="text-muted">{t("catalog.sub")}</p>
      </header>
      {data && !data.length && <Card className="text-center text-muted">{t("catalog.empty")}</Card>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {data?.map((c) => (
          <Link key={c.id} to={`/s/${c.share_token}`} className="group">
            <Card className="h-full space-y-2 transition group-hover:-translate-y-0.5 group-hover:border-accent">
              <span className="text-4xl">{c.cover_emoji}</span>
              <h3 className="font-display text-lg font-bold leading-tight">{c.title}</h3>
              <p className="line-clamp-3 text-sm text-muted">{c.description}</p>
              <p className="text-xs text-muted">{t(`learn.levels.${c.level}`)} · {t("catalog.lessons", { count: c.lessons })} · {t("catalog.by", { name: c.creator })}</p>
              <p className="flex items-center gap-1 text-xs text-muted"><Users className="h-3.5 w-3.5" /> {t("lab.learners", { count: c.learners })}</p>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
