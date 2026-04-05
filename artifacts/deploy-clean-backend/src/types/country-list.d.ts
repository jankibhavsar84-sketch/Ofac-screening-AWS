declare module "country-list" {
  export type CountryItem = {
    code: string;
    name: string;
  };

  export function getData(): CountryItem[];
}
