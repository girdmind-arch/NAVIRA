import {
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
} from "libphonenumber-js";

const regionNames = typeof Intl.DisplayNames === "function"
  ? new Intl.DisplayNames(["en"], { type: "region" })
  : null;

export const countries = getCountries()
  .map((code) => ({
    code,
    name: regionNames?.of(code) || code,
    callingCode: getCountryCallingCode(code),
    flag: String.fromCodePoint(...[...code].map((letter) => letter.charCodeAt(0) + 127397)),
  }))
  .sort((a, b) => a.name.localeCompare(b.name));

function getCountryCode(value) {
  if (typeof value !== "string" || !value.trim()) return "";
  const normalized = value.trim().toUpperCase();
  const matchingCode = countries.find(({ code }) => code === normalized);
  if (matchingCode) return matchingCode.code;

  const matchingName = countries.find(({ name }) => name.toUpperCase() === normalized);
  return matchingName?.code || "";
}

export function getPreferredCountry(profile) {
  const profileCountry = [
    profile?.country_code,
    profile?.countryCode,
    profile?.country,
    profile?.location?.country_code,
    profile?.location?.country,
  ].map(getCountryCode).find(Boolean);
  if (profileCountry) return profileCountry;

  const locales = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const locale of locales) {
    if (typeof locale !== "string" || !locale) continue;
    try {
      const region = new Intl.Locale(locale).region;
      const matchingCountry = getCountryCode(region || "");
      if (matchingCountry) return matchingCountry;
    } catch {
      const region = locale.match(/[-_]([A-Za-z]{2})(?:$|[-_])/);
      const matchingCountry = getCountryCode(region?.[1] || "");
      if (matchingCountry) return matchingCountry;
    }
  }
  return "";
}

export async function validatePhoneNumber(value, countryCode) {
  if (!countryCode) {
    return { error: "Select a country and dialing code." };
  }
  if (!value.trim()) {
    return { error: "Enter a phone number." };
  }

  const { parsePhoneNumberFromString: parsePhoneNumber } = await import("libphonenumber-js/max");
  const phone = parsePhoneNumber(value.trim(), countryCode);
  const country = countries.find(({ code }) => code === countryCode);
  if (!phone || phone.country !== countryCode || !phone.isValid()) {
    return { error: `Enter a valid ${country?.name || "selected country"} phone number.` };
  }
  return { number: phone.number };
}

export function getSavedPhoneNumber(value, countryCode) {
  const phone = parsePhoneNumberFromString(value, countryCode || undefined);
  return phone?.number || `raw:${value.replace(/\D/g, "")}`;
}

export function getEditablePhone(value, preferredCountry) {
  const phone = parsePhoneNumberFromString(value, preferredCountry || undefined);
  if (!phone) return { country: preferredCountry, value };
  return {
    country: phone.country || preferredCountry,
    value: phone.nationalNumber,
  };
}
