import { useQuery } from "@tanstack/react-query";

import { orgs, type MyAssignment } from "@/lib/orgs";

export function useMyAssignments() {
  return useQuery({ queryKey: ["my-assignments"], queryFn: orgs.myAssignments });
}

/** Scenario id → its assignment (for badges on the regular scenario cards). */
export function useScenarioAssignments(): Map<number, MyAssignment> {
  const { data } = useMyAssignments();
  return new Map((data ?? []).filter((a) => a.scenario).map((a) => [a.scenario!.id, a]));
}
