export interface ConsentValue { accept: boolean; age_band: "adult" | "minor" | ""; guardian_email: string }
export const emptyConsent: ConsentValue = { accept: false, age_band: "", guardian_email: "" };
export const consentReady = (c: ConsentValue) => c.accept && !!c.age_band && (c.age_band === "adult" || /\S+@\S+\.\S+/.test(c.guardian_email));
