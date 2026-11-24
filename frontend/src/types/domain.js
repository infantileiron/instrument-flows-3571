/** @typedef {{code: string, name: string, manager: string, purpose: string}} Hall */
/** @typedef {{code: string, name: string, unit: string}} Instrument */
/** @typedef {{halls: Hall[], instruments: Instrument[]}} Catalog */
/** @typedef {{username: string, display_name: string, role: 'analyst'|'reviewer'|'observer'}} User */
/** @typedef {{original_id: number, quantity: number, original_reference?: string, source?: string, destination?: string, instrument?: string}} ReversalLine */
/** @typedef {{id: number, reference: string, kind: 'loan'|'reversal', effective_on: string, quantity: number|null, reversed_quantity?: number, reversed_by?: string|null, line_total?: number, lines?: ReversalLine[], signature_valid: boolean}} Receipt */
/** @typedef {{reference: string, effective_on: string, lines: {original_reference: string, source: string, destination: string, instrument: string, quantity: number}[]}} ReversalDetail */
