/** Small presentation helper shared by service scenario screens. */
export const demoText = (value: string, options?: Record<string, unknown>) => options
    ? value.replace(/{{\s*(\w+)\s*}}/g, (_, key: string) => String(options[key] ?? ''))
    : value;
