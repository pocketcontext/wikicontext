import { expect, test } from "vitest";
import type { PageSummary } from "./types";
import { classifyWelcomePage, filterWelcomePages, groupWelcomePages, onboardingPages, WELCOME_TOPICS } from "./welcome";

function page(title: string, kind = "concept"): PageSummary {
  const slug = title.toLowerCase().replaceAll(" ", "-");
  return { id: `revision-${slug}`, page: `page-${slug}`, slug, title, kind, summary: "" };
}

test("every catalog page is included exactly once, including unknown subjects beyond 100 pages", () => {
  const pages = Array.from({ length: 150 }, (_, index) => page(`Unclassified ${index}`));
  const groups = groupWelcomePages(pages);
  expect(groups.map(group => group.id)).toEqual(WELCOME_TOPICS.map(topic => topic.id));
  const included = groups.flatMap(group => group.pages);
  expect(included).toHaveLength(150);
  expect(new Set(included.map(item => item.page)).size).toBe(150);
  expect(groups.find(group => group.id === "other")!.pages).toHaveLength(150);
  expect(groupWelcomePages([...pages].reverse())).toEqual(groups);
});

test("generic categories use title, slug and kind, with more specific historical intent first", () => {
  const fixtures = [
    ["New colleague onboarding", "getting-started"],
    ["Business strategy", "company-strategy"],
    ["Application workflow", "apps-workflows"],
    ["Platform architecture", "platform-security"],
    ["Customer relationships", "people-relationships"],
    ["Application proposal", "research-proposals"],
    ["Security meeting notes", "meetings-notes"],
    ["Onboarding release handoff", "handoffs-history"],
    ["Unfamiliar subject", "other"],
  ];
  for (const [title, category] of fixtures) expect(classifyWelcomePage(page(title))).toBe(category);
  expect(classifyWelcomePage({ ...page("Unfamiliar subject"), slug: "deployment-reference" })).toBe("platform-security");
  expect(classifyWelcomePage(page("Unfamiliar subject", "meeting"))).toBe("meetings-notes");
});

test("onboarding suggestions rank actual guides, omit historic mentions, and invent no links", () => {
  const pages = [page("Skills guide"), page("Login guide"), page("Device setup"), page("Team manual"), page("Colleague onboarding"), page("Onboarding release"), page("Setup proposal"), page("Onboarding meeting")];
  expect(onboardingPages(pages).map(item => item.title)).toEqual(["Colleague onboarding", "Team manual", "Device setup", "Login guide", "Skills guide"]);
  expect(onboardingPages([page("Unfamiliar subject")])).toEqual([]);
  expect(onboardingPages([])).toEqual([]);
});

test("catalog filtering matches all terms across metadata and sorts without mutating inputs", () => {
  const pages = [page("Zulu workflow"), { ...page("Alpha workflow"), summary: "Connect the device" }, page("Beta handbook")];
  expect(filterWelcomePages(pages, " WORKFLOW ").map(item => item.title)).toEqual(["Alpha workflow", "Zulu workflow"]);
  expect(filterWelcomePages(pages, "device alpha")).toEqual([pages[1]]);
  expect(filterWelcomePages(pages, "absent")).toEqual([]);
  expect(filterWelcomePages(pages, "").map(item => item.title)).toEqual(["Alpha workflow", "Beta handbook", "Zulu workflow"]);
  expect(pages[0].title).toBe("Zulu workflow");
});

test("general onboarding entry points precede alphabetically earlier application guides", () => {
  const general = [page("Employee onboarding"), page("Colleague onboarding"), page("Team orientation"), page("Shared getting started")];
  const application = [page("AAA application onboarding"), page("AAA application manual")];
  const ordered = onboardingPages([...application, ...general]);
  expect(ordered.slice(0, general.length).map(item => item.page).sort()).toEqual(general.map(item => item.page).sort());
  expect(ordered.slice(general.length)).toEqual(application);
  expect(onboardingPages([...application, ...general].reverse())).toEqual(ordered);
});

test("dated singular source notes remain in the index but never become onboarding suggestions", () => {
  const note = page("2024 01 12 employee onboarding note");
  const kindNote = page("2024 01 13 setup", "note");
  const guide = page("Employee onboarding");
  expect(onboardingPages([note, kindNote, guide])).toEqual([guide]);
  expect(groupWelcomePages([note, kindNote, guide]).find(group => group.id === "meetings-notes")!.pages).toEqual([note, kindNote]);
});

test("groups contain only pages supplied by the publication selection", () => {
  const selected = page("Current workflow");
  // Archived and draft revisions never enter the API's PageSummary list.
  expect(groupWelcomePages([selected]).flatMap(group => group.pages)).toEqual([selected]);
  expect(groupWelcomePages([]).every(group => group.pages.length === 0)).toBe(true);
});
