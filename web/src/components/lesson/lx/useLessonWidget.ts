import { useQuery } from "@tanstack/react-query";

import { lx } from "@/lib/lx";

export function useLessonWidget(lessonId: number) {
  return useQuery({
    queryKey: ["lx-widget", lessonId],
    queryFn: () => lx.widget(lessonId),
    staleTime: 5 * 60_000, // frame URLs carry a 10-minute token; don't reload the widget on every focus
    refetchOnWindowFocus: false,
    refetchInterval: (q) => (q.state.data?.status === "generating" ? 2500 : false),
  });
}
