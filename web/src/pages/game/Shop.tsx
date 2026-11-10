import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Lock } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Card } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { gameKey } from "@/lib/game";
import { useMe, useUpdatePreferences } from "@/lib/useMe";
import { Kili } from "@/mascot/Kili";
import { sfx } from "@/mascot/sfx";
import { mascot } from "@/mascot/store";

interface ShopData {
  coins: number;
  level: number;
  items: { code: string; slot: "outfit" | "accessory"; name: string; price: number; level: number; owned: boolean; locked: boolean }[];
  freeze: { price: number; owned: number; max: number };
}

/** Wardrobe: try items on Kili, buy with coins, equip instantly. */
export default function ShopPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: me } = useMe();
  const update = useUpdatePreferences();
  const { data } = useQuery({ queryKey: ["shop"], queryFn: () => api<ShopData>("/api/game/shop/") });
  const [tryOn, setTryOn] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const m = me?.preferences.mascot;

  const buy = useMutation({
    mutationFn: (item: string) => api("/api/game/shop/buy/", { method: "POST", json: { item } }),
    onSuccess: (_d, item) => {
      sfx("correct");
      mascot.react("celebrate");
      setMsg(t("shop.bought"));
      void qc.invalidateQueries({ queryKey: ["shop"] });
      void qc.invalidateQueries({ queryKey: gameKey });
      const it = data?.items.find((i) => i.code === item);
      if (it) equip(it.code, it.slot);
    },
    onError: (e) => {
      mascot.react("hmm");
      const code = e instanceof ApiError ? (e.data?.code as string) : "";
      setMsg(t(`shop.errors.${code}`, { defaultValue: t("mentor.errors.generic") }));
    },
  });

  function equip(code: string, slot: "outfit" | "accessory") {
    if (!m) return;
    if (slot === "outfit") update.mutate({ mascot: { outfit: m.outfit === code ? "none" : code } });
    else update.mutate({ mascot: { accessories: m.accessories.includes(code) ? m.accessories.filter((a) => a !== code) : [...m.accessories, code] } });
  }

  const preview = (() => {
    if (!m) return { outfit: "none", accessories: [] as string[] };
    const it = data?.items.find((i) => i.code === tryOn);
    if (!it) return { outfit: m.outfit, accessories: m.accessories };
    return it.slot === "outfit" ? { outfit: it.code, accessories: m.accessories } : { outfit: m.outfit, accessories: [...new Set([...m.accessories, it.code])] };
  })();

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl font-extrabold">{t("shop.title")}</h1>
          <p className="text-muted">{t("shop.sub")}</p>
        </div>
        <span className="rounded-full bg-amber-100 px-4 py-2 font-bold text-amber-700">🪙 {data?.coins ?? 0}</span>
      </header>
      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <Card className="flex flex-col items-center gap-2 lg:sticky lg:top-20 lg:self-start">
          <Kili mood={tryOn ? "cheer" : "idle"} size={220} color={m?.color} outfit={preview.outfit} accessories={preview.accessories} />
          <p className="font-display text-xl font-bold">{m?.name}</p>
          {msg && <p role="status" className="text-center text-sm text-muted">{msg}</p>}
        </Card>
        <div className="space-y-6">
          {(["outfit", "accessory"] as const).map((slot) => (
            <Card key={slot}>
              <h2 className="mb-3 font-display text-xl font-bold">{t(`shop.slots.${slot}`)}</h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {data?.items.filter((i) => i.slot === slot).map((i) => {
                  const equipped = slot === "outfit" ? m?.outfit === i.code : m?.accessories.includes(i.code);
                  return (
                    <div key={i.code} onMouseEnter={() => setTryOn(i.code)} onMouseLeave={() => setTryOn(null)} onFocus={() => setTryOn(i.code)}
                      className={cn("flex flex-col items-center gap-2 rounded-2xl border-2 p-3 text-center", equipped ? "border-accent bg-accent/10" : "border-line")}>
                      <Kili mood="idle" size={70} color={m?.color} outfit={slot === "outfit" ? i.code : "none"} accessories={slot === "accessory" ? [i.code] : []} />
                      <p className="font-semibold leading-tight">{i.name}</p>
                      {i.owned ? (
                        <Button variant={equipped ? "primary" : "outline"} className="w-full py-1.5 text-sm" onClick={() => equip(i.code, slot)}>
                          {equipped ? <><Check className="h-4 w-4" /> {t("shop.wearing")}</> : t("shop.wear")}
                        </Button>
                      ) : i.locked ? (
                        <span className="flex items-center gap-1 text-xs font-semibold text-muted"><Lock className="h-3.5 w-3.5" /> {t("shop.unlockAt", { n: i.level })}</span>
                      ) : (
                        <Button className="w-full py-1.5 text-sm" disabled={(data?.coins ?? 0) < i.price} loading={buy.isPending && buy.variables === i.code} onClick={() => buy.mutate(i.code)}>
                          🪙 {i.price}
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            </Card>
          ))}
          <Card className="flex flex-wrap items-center gap-4">
            <span className="text-4xl">🧊</span>
            <div className="flex-1">
              <p className="font-bold">{t("shop.freeze")}</p>
              <p className="text-sm text-muted">{t("shop.freezeSub", { n: data?.freeze.owned ?? 0, max: data?.freeze.max ?? 2 })}</p>
            </div>
            <Button disabled={!data || data.freeze.owned >= data.freeze.max || data.coins < data.freeze.price} loading={buy.isPending && buy.variables === "streak_freeze"} onClick={() => buy.mutate("streak_freeze")}>
              🪙 {data?.freeze.price}
            </Button>
          </Card>
        </div>
      </div>
    </div>
  );
}
