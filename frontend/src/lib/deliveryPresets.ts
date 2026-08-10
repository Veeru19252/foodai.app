// Pan-India delivery presets for the checkout map picker.
//
// Mirrors tracking.DELIVERY_PRESETS in the backend exactly (same labels and
// coordinates) so a label sent as "customer_home" always resolves server-side.

export interface DeliveryPreset {
  label: string;
  city: string;
  address: string;
  lat: number;
  lng: number;
}

export const DELIVERY_PRESETS: DeliveryPreset[] = [
  // Bengaluru
  { label: "MG Road / Indiranagar", city: "Bengaluru", address: "Hostel Block C, MG Road", lat: 12.9719, lng: 77.6412 },
  { label: "Koramangala", city: "Bengaluru", address: "5th Block, Koramangala", lat: 12.9352, lng: 77.6245 },
  { label: "HSR Layout", city: "Bengaluru", address: "Sector 1, HSR Layout", lat: 12.9116, lng: 77.6387 },
  { label: "Whitefield", city: "Bengaluru", address: "ITPL Main Road, Whitefield", lat: 12.9698, lng: 77.75 },
  { label: "City Center", city: "Bengaluru", address: "MG Road Metro, City Center", lat: 12.977, lng: 77.596 },
  // New Delhi
  { label: "Connaught Place", city: "New Delhi", address: "Barakhamba Road, Connaught Place", lat: 28.6315, lng: 77.2167 },
  { label: "Karol Bagh", city: "New Delhi", address: "Ajmal Khan Road, Karol Bagh", lat: 28.6519, lng: 77.1909 },
  { label: "Saket", city: "New Delhi", address: "District Centre, Saket", lat: 28.5245, lng: 77.2066 },
  { label: "Dwarka", city: "New Delhi", address: "Sector 12, Dwarka", lat: 28.5857, lng: 77.0424 },
  // Mumbai
  { label: "Bandra West", city: "Mumbai", address: "Linking Road, Bandra West", lat: 19.0596, lng: 72.8295 },
  { label: "Andheri West", city: "Mumbai", address: "Lokhandwala, Andheri West", lat: 19.1364, lng: 72.8263 },
  { label: "Colaba", city: "Mumbai", address: "Shahid Bhagat Singh Road, Colaba", lat: 18.9169, lng: 72.8265 },
  { label: "Powai", city: "Mumbai", address: "Hiranandani Gardens, Powai", lat: 19.1176, lng: 72.906 },
  // Hyderabad
  { label: "Banjara Hills", city: "Hyderabad", address: "Road No 12, Banjara Hills", lat: 17.4156, lng: 78.4347 },
  { label: "Gachibowli", city: "Hyderabad", address: "Financial District, Gachibowli", lat: 17.4401, lng: 78.3489 },
  { label: "Madhapur", city: "Hyderabad", address: "Hitech City Road, Madhapur", lat: 17.4483, lng: 78.3915 },
  // Chennai
  { label: "T. Nagar", city: "Chennai", address: "Usman Road, T. Nagar", lat: 13.0418, lng: 80.2341 },
  { label: "Anna Nagar", city: "Chennai", address: "2nd Avenue, Anna Nagar", lat: 13.085, lng: 80.2101 },
  { label: "Velachery", city: "Chennai", address: "100 Feet Road, Velachery", lat: 12.9791, lng: 80.2208 },
  // Kolkata
  { label: "Park Street", city: "Kolkata", address: "Park Street Area", lat: 22.5528, lng: 88.3522 },
  { label: "Salt Lake", city: "Kolkata", address: "Sector V, Salt Lake", lat: 22.5806, lng: 88.4175 },
  { label: "Howrah", city: "Kolkata", address: "Grand Trunk Road, Howrah", lat: 22.5958, lng: 88.2636 },
  // Pune
  { label: "Koregaon Park", city: "Pune", address: "North Main Road, Koregaon Park", lat: 18.5362, lng: 73.894 },
  { label: "Hinjewadi", city: "Pune", address: "Phase 1, Hinjewadi", lat: 18.5913, lng: 73.7389 },
  { label: "Viman Nagar", city: "Pune", address: "Clover Park, Viman Nagar", lat: 18.5679, lng: 73.9143 },
  // Jaipur
  { label: "Malviya Nagar", city: "Jaipur", address: "Tonk Road, Malviya Nagar", lat: 26.8551, lng: 75.8099 },
  { label: "C-Scheme", city: "Jaipur", address: "Ashok Marg, C-Scheme", lat: 26.906, lng: 75.7856 },
  { label: "Vaishali Nagar", city: "Jaipur", address: "Amrapali Marg, Vaishali Nagar", lat: 26.9169, lng: 75.7402 },
  // Ahmedabad
  { label: "Satellite", city: "Ahmedabad", address: "Jodhpur Cross Road, Satellite", lat: 23.0333, lng: 72.5086 },
  { label: "Maninagar", city: "Ahmedabad", address: "Jawaharlal Nehru Road, Maninagar", lat: 23.012, lng: 72.5914 },
  { label: "Bodakdev", city: "Ahmedabad", address: "Sindhu Bhavan Road, Bodakdev", lat: 23.0452, lng: 72.51 },
];

// City centre anchors used to pan the checkout map when a city is selected.
export const CITY_CENTERS: Record<string, [number, number]> = {
  Bengaluru: [12.9716, 77.5946],
  "New Delhi": [28.6139, 77.209],
  Mumbai: [19.076, 72.8777],
  Hyderabad: [17.385, 78.4867],
  Chennai: [13.0827, 80.2707],
  Kolkata: [22.5726, 88.3639],
  Pune: [18.5204, 73.8567],
  Jaipur: [26.9124, 75.7873],
  Ahmedabad: [23.0225, 72.5714],
};

export const DEFAULT_CITY = "Bengaluru";
export const DEFAULT_PRESET = DELIVERY_PRESETS[0];

export const DEFAULT_POINT = {
  lat: DEFAULT_PRESET.lat,
  lng: DEFAULT_PRESET.lng,
  address: DEFAULT_PRESET.address,
};

/** Ordered list of cities that have presets (same order as the backend). */
export const DELIVERY_CITIES = Array.from(
  new Set(DELIVERY_PRESETS.map((p) => p.city))
);

/** State auto-fill for each preset city (used at checkout). */
export const STATE_BY_CITY: Record<string, string> = {
  Bengaluru: "Karnataka",
  "New Delhi": "Delhi",
  Mumbai: "Maharashtra",
  Hyderabad: "Telangana",
  Chennai: "Tamil Nadu",
  Kolkata: "West Bengal",
  Pune: "Maharashtra",
  Jaipur: "Rajasthan",
  Ahmedabad: "Gujarat",
};

/** Group presets by city, preserving the backend's city order. */
export function presetsByCity(): { city: string; presets: DeliveryPreset[] }[] {
  const order: string[] = [];
  const grouped = new Map<string, DeliveryPreset[]>();
  for (const p of DELIVERY_PRESETS) {
    if (!grouped.has(p.city)) {
      grouped.set(p.city, []);
      order.push(p.city);
    }
    grouped.get(p.city)!.push(p);
  }
  return order.map((city) => ({ city, presets: grouped.get(city)! }));
}

/** Return a preset by exact label (used to resolve saved/selected points). */
export function presetByLabel(label: string): DeliveryPreset | undefined {
  return DELIVERY_PRESETS.find((p) => p.label === label);
}
