# ANTLR XML Grammar ↔ mxml (Mini-XML) Comparison

## Overview

This document compares the **ANTLR reference XML grammar** (from `antlr/grammars-v4`) against the **Mini-XML (mxml) C library** to determine what XML features the grammar generates versus what mxml actually accepts. This comparison drives the Agentic-Fuzzing project's Hypothesis-based generator: the generator must produce inputs that mxml can parse, and mxml is more permissive in some areas and stricter in others compared to the ANTLR grammar.

**Source references:**
- **ANTLR grammar source:** https://github.com/antlr/grammars-v4/tree/master/xml (`XMLLexer.g4`, `XMLParser.g4`, BSD license, Terence Parr 2013)
- **mxml source:** https://github.com/michaelrsweet/mxml — vendored at commit `e6824d899d949387fb0156af6f4101373b9be519`
- **Support documentation:** http://pldb.info/concepts/xml (referenced in the grammar's own readme; currently unreachable)

The original grammar files are verbatim copies from the ANTLR upstream and live in `grammar/original/`.

---

## ANTLR Grammar Quick Reference

The ANTLR grammar consists of two files that work together:

- **`XMLLexer.g4`** — 93 lines, 3 lexer modes
- **`XMLParser.g4`** — 78 lines, 8 parser rules

### Lexer Modes

| Mode | Purpose |
|---|---|
| **Default** (outside tags) | Handles `COMMENT`, `CDATA`, `DTD`, `EntityRef`, `CharRef`, `SEA_WS`, `OPEN`, `XMLDeclOpen`, `SPECIAL_OPEN`, `TEXT` |
| **INSIDE** (inside a tag) | Handles `CLOSE`, `SPECIAL_CLOSE`, `SLASH_CLOSE`, `SLASH`, `EQUALS`, `STRING`, `Name`, `S` |
| **PROC_INSTR** (processing instructions) | Handles `PI`, `IGNORE` |

### Key Tokens

| Token | Pattern | Notes |
|---|---|---|
| `COMMENT` | `<!-- ... -->` | |
| `CDATA` | `<![CDATA[ ... ]]>` | |
| `DTD` | `<! ... >` | `→ skip` — discarded entirely |
| `EntityRef` | `&Name;` | Any named entity |
| `CharRef` | `&#DIGIT+;` or `&#xHEXDIGIT+;` | Decimal or hex char ref |
| `SEA_WS` | `(' ' | '\t' | '\r?\n')+` | Significant whitespace (kept) |
| `OPEN` | `<` | Pushes INSIDE mode |
| `XMLDeclOpen` | `<?xml S` | Pushes INSIDE mode |
| `SPECIAL_OPEN` | `<?Name` | Accumulates, pushes PROC_INSTR |
| `TEXT` | `~[<&]+` | Any char except `<` and `&` |
| `STRING` | `"~[<"]*"` or `'~[<']*` | Quoted attribute value |
| `Name` | `NameStartChar NameChar*` | Full Unicode XML Name production |
| `S` | `[ \t\r\n]` | Skipped inside tags |

### Parser Rules

```
document  : prolog? misc* element misc* EOF
prolog    : XMLDeclOpen attribute* SPECIAL_CLOSE
content   : chardata? ((element | reference | CDATA | PI | COMMENT) chardata?)*
element   : < Name attribute* > content < / Name > | < Name attribute* />
reference : EntityRef | CharRef
attribute : Name = STRING
chardata  : TEXT | SEA_WS
misc      : COMMENT | PI | SEA_WS
```

---

## mxml Quick Reference

**Mini-XML** is a lightweight C library for XML parsing and tree manipulation. From its README:

> "Mini-XML doesn't do validation or other types of processing on the data based upon schema files or other sources of definition information."

### Node Types (`mxml_type_t`)

| Type | Description |
|---|---|
| `MXML_IGNORE` | Dropped node |
| `MXML_ELEMENT` | `<name>` element |
| `MXML_TEXT` | Plain text content |
| `MXML_CDATA` | `<![CDATA[...]]>` |
| `MXML_COMMENT` | `<!--...-->` |
| `MXML_DECLARATION` | `<!...>` (includes `<?xml...>`) |
| `MXML_DIRECTIVE` | `<?...?>` processing instruction |
| `MXML_INTEGER` | Integer leaf value |
| `MXML_REAL` | Real/float leaf value |
| `MXML_OPAQUE` | Opaque string leaf value |
| `MXML_CUSTOM` | User-defined type |

### Encoding Support

- **Reads:** UTF-8, UTF-16-BE (BOM `0xFE 0xFF`), UTF-16-LE (BOM `0xFF 0xFE`)
- **Writes:** UTF-8 only
- Rejects invalid multi-byte sequences with error: *"Bad control character ... not allowed by XML standard"*

### Key API

- Load: `mxmlLoadString()`, `mxmlLoadFd()`, `mxmlLoadFile()`, `mxmlLoadFilename()`
- Create: `mxmlNewElement()`, `mxmlNewText()`, `mxmlNewCDATA()`, `mxmlNewComment()`, etc.
- Find: `mxmlFindElement()`, `mxmlFindPath()`

---

## Feature Comparison Table

This is the core reference for the fuzzer generator. Each row answers: *does mxml accept what the ANTLR grammar produces for this feature?*

| Feature | ANTLR Grammar | mxml Behavior | Generator Action |
|---|---|---|---|
| **XML Declaration** (`<?xml version="1.0"?>`) | `XMLDeclOpen` → `prolog` rule | Stored as **DIRECTIVE** node. Must be the first node to become the document parent (`mxmlLoadString` treats it as root). | ✅ Safe — emit as first node |
| **Processing Instructions** (`<?...?>`) | `SPECIAL_OPEN` + `PROC_INSTR` → `PI` token | Stored as **DIRECTIVE** node. If content starts with `xml ` (case-sensitive, with space) and is first node, becomes parent. Otherwise a child directive. | ✅ Safe — emit as opaque directive |
| **Comments** (`<!--...-->`) | `COMMENT` token | **COMMENT** node. Requires well-formed `--\>` terminator. Rejects early EOF with error: *"Early EOF in comment node."* | ✅ Safe — emit well-formed comments |
| **CDATA Sections** (`<![CDATA[...]]>`) | `CDATA` token | **CDATA** node. Reads until `]]>` terminator. Preserves raw content verbatim. | ✅ Safe — emit CDATA with proper terminator |
| **DTD / DOCTYPE** (`<!DOCTYPE ...>`) | `DTD` token → `→ skip` (discarded, not in parse tree) | **DECLARATION** node (opaque string). Never interpreted, validated, or used. Stored as literal text. | ⚠️ Include as opaque — won't be rejected, but has no semantic effect in mxml |
| **Entity Declarations** (`<!ENTITY ...>`) | `DTD` → `skip` (discarded) | **DECLARATION** node (opaque). Never expanded. | ⚠️ Include as opaque — won't be rejected |
| **Notation Declarations** (`<!NOTATION ...>`) | `DTD` → `skip` (discarded) | **DECLARATION** node (opaque). | ⚠️ Include as opaque — won't be rejected |
| **Entity References** (`&name;`) | `EntityRef` — syntactically matches any `Name` | Only **5 built-ins** accepted: `amp`, `lt`, `gt`, `quot`, `apos` (added in v4.0.5). Any other named entity → **ERROR**: *"Entity '&name;' not supported."* | ⚠️ **Must constrain** to built-in names only |
| **Character References** (`&#N;`, `&#xN;`) | `CharRef` — decimal or hex | Resolved to character value. Rejects unterminated refs and control chars in entity values. | ✅ Safe — emit numeric refs freely |
| **Element Names** | Strict `NameStartChar NameChar*` (full Unicode range) | Permissive scanner: accepts names the ANTLR grammar would reject (e.g. leading digits, punctuation). Only rejects bare `<` and chars < `'0'` not in `{!, -, ., /}`. | ✅ ANTLR names are a strict subset — safe |
| **Attribute Values** (quoted) | `STRING` — double or single quoted | Supports both quoted and **unquoted** values. Quoted values are safe. | ✅ Safe — emit quoted attributes |
| **Unquoted Attribute Values** | Not in grammar | Supported but not generated by the grammar | N/A |
| **Self-Closing Tags** (`<x/>`) | `< Name attribute* />` | Supported. Requires `>` immediately after `/`. Error if missing: *"Expected '>' after '/'".* | ✅ Safe |
| **Mismatched Close Tags** | `element` rule enforces matching `Name` | **ERROR**: *"Mismatched close tag '<foo>' under parent '<bar>'."* | ✗ Grammar already prevents this structurally |
| **Duplicate Attributes** | `Name = STRING` — no uniqueness enforced | **ERROR**: *"Duplicate attribute 'x' in element y."* | ✗ Generator should avoid duplicates |
| **Bare `<` in Element Names** | `Name` requires `NameStartChar` | **ERROR**: *"Bare '<' in element"* | ✗ Grammar already prevents |
| **Missing `>` after `/`** | `SLASH_CLOSE` rule enforces it | **ERROR**: *"Expected '>' after '/'".* | ✗ Grammar already enforces |
| **Missing Attribute Value** | `Name = STRING` requires `=` and value | **ERROR**: *"Missing value for attribute."* | ✗ Grammar already enforces |
| **Whitespace** (`SEA_WS`, spaces, tabs) | `SEA_WS` token kept; `S` skipped inside tags | Preserved as **TEXT** nodes (with `whitespace=true` flag). Custom whitespace callback available. | ✅ Safe |
| **XML Namespaces** (`xmlns`, `xml:foo`) | Not modeled in grammar | Treated as ordinary attribute/element names. **No URI binding or prefix resolution**. | ✅ Names work; namespace semantics are ignored |
| **Encodings** | N/A (grammar-agnostic) | Reads UTF-8 and UTF-16 (BOM-detected). Writes UTF-8. Invalid multi-byte sequences → error. `encoding="iso-8859-1"` in declaration is **ignored** (bytes still decoded as UTF-8). | ✅ Use UTF-8; avoid encoding declarations |
| **Bad Control Characters** (<0x20 except `\n\r\t`) | `TEXT: ~[<&]+` accepts **any** non-`<`/`&` char | **ERROR**: *"Bad control character 0xXX not allowed by XML standard"* | ✗ **Must avoid** raw control chars in text content |
| **Single Root Element** | `document` requires exactly one `element` | First node becomes root; any second top-level node → **ERROR**: *"cannot be a second root node after <foo>."* | ✗ Grammar already guarantees single root |
| **Integer/Real/Opaque Leaf Values** | Text content only | Optional `type` callback maps text to INTEGER/REAL/OPAQUE. Without callback, everything is **TEXT**. | ✅ Works as text; type callback is external configuration |
| **Custom Nodes** | None | `MXML_CUSTOM` node type via load/save callbacks | N/A — custom code |

---

## Key Differences Summary

These are the most important divergences for the fuzzer generator:

1. **DTD is discarded by ANTLR but preserved by mxml.** The ANTLR lexer rule `DTD: '<!' .*? '>' → skip;` silently discards all DTD content. mxml, by contrast, stores `<!...>` blocks as opaque **DECLARATION** nodes. The fuzzer **should include** DTD/DOCTYPE content in generated inputs to test mxml's robustness with opaque declaration handling.

2. **Entity references — the critical constraint.** The ANTLR grammar syntactically accepts *any* `&name;` reference. mxml **only accepts 5 built-in entities** (`amp`, `lt`, `gt`, `quot`, `apos`) plus numeric character references. Any other named entity causes a parse error. **The generator must constrain entity references to these 5 names and `&#N;`/`&#xN;` forms only.**

3. **Element names — mxml is more permissive.** The ANTLR `Name` production with its full Unicode `NameStartChar`/`NameChar` ranges is stricter than mxml's scanner. All names the grammar generates are accepted by mxml. No constraint adjustment needed.

4. **Attribute values — quoted is safe.** The ANTLR grammar requires quoted attribute values (`"..."` or `'...'`). mxml accepts both quoted and unquoted values. Grammar output is a safe subset.

5. **Control characters — the hidden trap.** ANTLR's `TEXT: ~[<&]+` token accepts any 16-bit character except `<` and `&`. mxml **rejects** control characters below `0x20` (except `\n`, `\r`, `\t`) everywhere including text content and entity values. **The generator must avoid raw control characters in text and entity content.**

6. **UTF-8 well-formedness.** mxml validates multi-byte UTF-8 sequences and rejects invalid ones. The ANTLR grammar has no encoding awareness. **The generator should emit only valid UTF-8.**

7. **Mismatched tags, duplicate attributes, missing values** — all rejected by mxml, but the ANTLR grammar already prevents these structurally through its rules. No extra constraints needed.

8. **Single root** — enforced by both the grammar and mxml. No extra work needed.

---

## Generator / Constraints Guidance for the Fuzzer

### ✅ Safe to emit (no mxml rejection risk)

- XML declaration: `<?xml version="1.0" encoding="UTF-8"?>`
- Comments: `<!-- ... -->` (well-formed with `--\>` terminator)
- CDATA: `<![CDATA[ ... ]]>` (proper terminator)
- Processing instructions: `<?target data?>`
- DTD blocks: `<!DOCTYPE ...>`, `<!ENTITY ...>`, `<!ELEMENT ...>` — stored opaquely
- Element names using the ANTLR `Name` production
- Quoted attribute values (single or double quotes)
- Self-closing tags: `<name attr="val"/>`
- Built-in entity references: `&lt;`, `&amp;`, `&gt;`, `&quot;`, `&apos;`
- Numeric character references: `&#N;`, `&#xN;`
- Whitespace (spaces, tabs, newlines)
- Valid UTF-8 text content

### ❌ Must avoid (will cause mxml rejection)

- **Custom/unknown entity names** (`&foo;`, `&unknown;`) — the #1 source of parse errors
- **Raw control characters** in text or entity content (chars < `0x20` except `\n`, `\r`, `\t`)
- Mismatched close tags (grammar already prevents)
- Duplicate attribute names on the same element (generator should deduplicate)
- Malformed comment/CDATA/PI/declaration terminators (grammar already prevents)
- Invalid UTF-8 byte sequences (generator should emit valid UTF-8 only)
- Second top-level root node (grammar already prevents)

### 🔧 Recommended generator practices

- Use valid UTF-8 for all text content
- Keep element names within the ANTLR `Name` production for maximum safety
- Use double-quoted attribute values (slightly more common in practice)
- Include DTD blocks in fuzzing to test mxml's opaque declaration handling
- Explicitly constrain entity references to the 5 built-ins + numeric refs
- Avoid generating raw control characters in any context

---

## Source Code References

Findings are traced to these source locations in the vendored mxml at commit `e6824d899d949387fb0156af6f4101373b9be519`:

| Finding | Source File | Function / Lines |
|---|---|---|
| Entity resolution, built-in list (`amp`, `lt`, `gt`, `quot`, `apos`) | `target/mxml/mxml-file.c` | `_mxml_entity_string()`, `_mxml_entity_value()` (~line 540–555) |
| Entity reference parsing in text | `target/mxml/mxml-file.c` | `mxml_get_entity()` (~line 556–615) |
| Control-char rejection (`mxml_bad_char`) | `target/mxml/mxml-file.c` | `mxml_bad_char()` macro (~line 600) |
| Encoding detection (UTF-8, UTF-16 BE/LE BOM) | `target/mxml/mxml-file.c` | `mxml_getc()` (~line 622–794) |
| Main load state machine | `target/mxml/mxml-file.c` | `mxml_load_data()` (~line 801–1447) |
| Element/attribute parsing | `target/mxml/mxml-file.c` | `mxml_parse_element()` (~line 1455–1717) |
| Comment parsing (`--\>` terminator check) | `target/mxml/mxml-file.c` | `mxml_load_data()` comment branch (~line 950–980) |
| CDATA parsing (`]]>` terminator) | `target/mxml/mxml-file.c` | `mxml_load_data()` CDATA branch (~line 980–1010) |
| Mismatched close tag error | `target/mxml/mxml-file.c` | `mxml_load_data()` close tag branch (~line 1100–1150) |
| Second root node error | `target/mxml/mxml-file.c` | `mxml_load_data()` root enforcement (~line 820–850) |
| Duplicate attribute error | `target/mxml/mxml-file.c` | `mxml_parse_element()` (~line 1560–1600) |
| Node type enum (`mxml_type_t`) | `target/mxml/mxml.h` | `mxml_type_t` (~line 44–55) |
| SAX event enum (`mxml_sax_event_t`) | `target/mxml/mxml.h` | `mxml_sax_event_t` (~line 33–42) |
| Public load/save API | `target/mxml/mxml.h` | `mxmlLoadString`, `mxmlSaveString`, etc. |
| Node creation API | `target/mxml/mxml-node.c` | `mxmlNewXML`, `mxmlNewElement`, `mxmlNewText`, etc. |
| mxml feature list / validation disclaimer | `target/mxml/README.md` | Paragraph on no DTD/schema validation |

---

## Canonical Valid mxml Example

The following is the canonical fuzzing seed from `target/mxml/afl-input/test.xml`. It demonstrates all features that should be safe for the generator to emit:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<group>
<option>
<keyword type="opaque">InputSlot</keyword>
<default type="opaque">Auto</default>
<text>Media Source</text>
<order type="real">10.000000</order>
<choice>
<keyword type="opaque">Auto</keyword>
<text>Auto Tray Selection</text>
<code type="opaque"/>
</choice>
<choice>
<keyword type="opaque">Upper</keyword>
<text>Tray1</text>
<code type="opaque">&lt;&lt;/MediaPosition0&gt;&gt;setpagedevice</code>
</choice>
<choice>
<keyword type="opaque">Lower</keyword>
<text>Tray2</text>
<code type="opaque">&lt;&lt;/MediaPosition1&gt;&gt;setpagedevice</code>
</choice>
</option>
<integer>123</integer>
<string>Now is the time for all good men to come to the aid of their country.</string>
<!-- this is a comment -->
<![CDATA[this is CDATA0123456789ABCDEF]]>
</group>
```

Key observations for the generator:
- Uses the XML declaration as the root/parent node
- Entity references use only `&lt;` and `&gt;` (built-ins)
- Self-closing tag `<code type="opaque"/>` is valid
- Comment and CDATA are well-formed
- Nested elements are properly balanced
- This is a CUPS PPD-style document; the `type` attribute is a convention handled by an external callback, not by mxml itself

---

## AFL Dictionary Tokens

The vendored `target/mxml/xml.dict` (73 tokens) is used by AFL/libFuzzer-guided fuzzing. It contains vocabulary that mxml accepts as opaque declarations or literal text, including DTD-related tokens (`<!DOCTYPE`, `<!ENTITY`, `<!ATTLIST`, `<!ELEMENT`, `<!NOTATION`, `<![IGNORE[`, `<![INCLUDE[`) and attribute names (`xmlns`, `xml:lang`, `xml:space`, `version`, `encoding`). These are all safe to include in generated inputs since mxml treats them opaquely inside `<!...>` blocks.
