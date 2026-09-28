// Profile -> field mappings shared by the content script and the U7/U8
// adapters. Site-agnostic (R5); adapters filter these to the controls present
// on the current step and flag what they cannot fill (R10).

export function buildProfileMappings(packet) {
  const profile = (packet && packet.profile) || {};
  const mappings = [
    {
      descriptor: { label: "Full name", name: "name", autocomplete: "name" },
      value: profile.full_name,
    },
    {
      descriptor: { label: "Email", name: "email", autocomplete: "email", type: "email" },
      value: profile.email,
    },
    {
      descriptor: { label: "Phone", name: "phone", autocomplete: "tel", type: "tel" },
      value: profile.phone,
    },
    {
      descriptor: { label: "Address", name: "address", autocomplete: "street-address" },
      value: profile.address,
    },
    {
      descriptor: { label: "LinkedIn", name: "linkedin" },
      value: profile.linkedin,
    },
    {
      descriptor: { label: "Website", name: "website", autocomplete: "url" },
      value: profile.website,
    },
    {
      descriptor: { label: "Summary", name: "summary" },
      value: profile.summary,
    },
  ];
  const cv = ((packet && packet.documents) || []).find((document) => document.kind === "cv");
  if (cv) {
    mappings.push({
      descriptor: { label: "Resume", name: "resume", type: "file" },
      kind: "file",
      document: cv,
    });
  }
  return mappings;
}
