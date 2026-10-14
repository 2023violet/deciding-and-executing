#!/usr/bin/env python3
"""Independent, read-only *static* evidence triage (Python standard library only).

This helper never executes inspected project code, never proves semantic correctness,
and never issues human approval. Only listed contract probes are inspected.
"""
import argparse
import ast
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote

MAX_BYTES = 2 * 1024 * 1024
MAX_CONTRACT = 1024 * 1024
TYPES = {'file_exists', 'python_syntax', 'markdown_links', 'html_form_labels', 'sha256', 'manual'}

class ContractError(ValueError):
    pass


def resolve_path(root, raw):
    if not isinstance(raw, str) or not raw or '\\' in raw or raw.startswith('/'):
        raise ContractError('invalid relative path')
    p = PurePosixPath(raw)
    if any(part in ('.', '..') for part in raw.split('/')) or not p.parts:
        raise ContractError('invalid relative path')
    candidate = (root / raw).resolve()
    if not candidate.is_relative_to(root):
        raise ContractError('path escapes review root')
    return candidate


def read_limited(path):
    if not path.is_file():
        raise FileNotFoundError('file not found')
    if path.stat().st_size > MAX_BYTES:
        raise ContractError('file too large for automatic probe')
    return path.read_bytes()


class FormNames(HTMLParser):
    """Conservative name heuristic, NOT an accessible-name algorithm/browser audit."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.controls = []
        self.text_by_id = {}
        self.labels = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        element = {'tag': tag, 'id': a.get('id'), 'text': [], 'for': a.get('for')}
        self.stack.append(element)
        if tag == 'label':
            self.labels.append(element)
        if tag in ('input', 'select', 'textarea'):
            if tag == 'input' and (a.get('type') or 'text').lower() in ('hidden', 'button', 'submit', 'reset', 'image'):
                return
            self.controls.append({'tag': tag, 'id': a.get('id'),
                'aria': a.get('aria-label'), 'labelledby': a.get('aria-labelledby'),
                'title': a.get('title'), 'wrappers': [e for e in self.stack if e['tag'] == 'label']})

    def handle_data(self, data):
        for element in self.stack:
            element['text'].append(data)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i]['tag'] == tag:
                completed = self.stack[i:]
                self.stack = self.stack[:i]
                for element in completed:
                    if element['id']:
                        self.text_by_id[element['id']] = ''.join(element['text']).strip()
                break

    def finalize(self):
        for element in self.stack:
            if element['id']:
                self.text_by_id[element['id']] = ''.join(element['text']).strip()
        def named(c):
            if (c['aria'] or '').strip() or (c['title'] or '').strip():
                return True
            refs = (c['labelledby'] or '').split()
            if refs and all(self.text_by_id.get(ref, '').strip() for ref in refs):
                return True
            if c['id'] and any(e['for'] == c['id'] and ''.join(e['text']).strip() for e in self.labels):
                return True
            if any(''.join(e['text']).strip() for e in c['wrappers']):
                return True
            return False
        return [f"{c['tag']}#{c['id'] or '?'}" for c in self.controls if not named(c)]


def markdown_issues(root, data, base):
    issues=[]
    # Inline links only. Deliberately not a complete CommonMark implementation.
    for match in re.finditer(r'(?<!!)\[[^\]]*\]\(([^)]+)\)', data.decode('utf-8')):
        dest=match.group(1).strip().split(' "')[0].strip('<>')
        if not dest or dest.startswith(('#','http://','https://','mailto:','data:','tel:')):
            continue
        local=unquote(dest.split('#')[0].split('?')[0])
        if not local:
            continue
        try:
            target=(base/local).resolve()
            if not target.is_relative_to(root) or not target.exists():
                issues.append(local)
        except (ValueError,OSError):
            issues.append(local)
    return issues


def run_probe(root, probe):
    kind=probe['type']
    if kind == 'manual':
        return 'NOT_VERIFIED', 'Requires independent observation; automatic probe cannot satisfy this requirement', None
    path=resolve_path(root,probe['path'])
    if kind == 'file_exists':
        exists=path.is_file()
        return ('PASS' if exists else 'FAIL'), ('file exists' if exists else 'file missing'), None
    data=read_limited(path)
    digest=hashlib.sha256(data).hexdigest()
    if kind == 'sha256':
        matched=digest == probe['expected_sha256'].lower()
        return ('PASS' if matched else 'FAIL'), ('SHA-256 matches' if matched else 'SHA-256 mismatch'), digest
    if kind == 'python_syntax':
        try:
            ast.parse(data.decode('utf-8'), filename=probe['path'])
            return 'PASS', 'Python parsed; functional behavior NOT verified', digest
        except (SyntaxError,UnicodeDecodeError):
            return 'FAIL', 'Python parse failed', digest
    if kind == 'markdown_links':
        try:
            issues=markdown_issues(root,data,path.parent)
        except UnicodeDecodeError:
            return 'FAIL','Markdown is not UTF-8',digest
        return ('FAIL' if issues else 'PASS'), ('Missing/outside local links: '+', '.join(issues[:12]) if issues else 'No missing inline links in narrow parser; semantics NOT verified'),digest
    if kind == 'html_form_labels':
        try:
            scanner=FormNames();scanner.feed(data.decode('utf-8'))
            missing=scanner.finalize()
        except (UnicodeDecodeError,ValueError):
            return 'FAIL','HTML could not be parsed as UTF-8',digest
        return ('FAIL' if missing else 'PASS'), ('Controls without detectable nonempty name: '+', '.join(missing) if missing else 'No unlabeled controls detected by heuristic; browser a11y NOT checked'),digest
    raise ContractError('unsupported probe')


def validate_contract(contract):
    if not isinstance(contract,dict) or contract.get('schema_version') not in (1,2):
        raise ContractError('schema_version must be 1 or 2')
    version=contract['schema_version']
    criteria=contract.get('criteria')
    if not isinstance(criteria,list) or not criteria:
        raise ContractError('criteria must be a nonempty list')
    expected={}
    if version == 2:
        src=contract.get('requirements_source')
        if not isinstance(src,dict) or not all(isinstance(src.get(x),str) and src[x].strip() for x in ('kind','reference')):
            raise ContractError('requirements_source.kind and .reference are required (origin NOT authenticated)')
        requirements=contract.get('requirements')
        if not isinstance(requirements,list) or not requirements:
            raise ContractError('requirements must be nonempty list')
        for r in requirements:
            if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not r['id'].strip() or not isinstance(r.get('text'),str) or not r['text'].strip() or r['id'] in expected:
                raise ContractError('requirement id must be unique and text nonempty')
            expected[r['id']]=r['text']
    seen=set(); covered=set()
    for c in criteria:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not c['id'].strip() or c['id'] in seen:
            raise ContractError('criterion id must be unique and nonempty')
        seen.add(c['id'])
        if version == 1:
            if not isinstance(c.get('requirement'),str) or not c['requirement'].strip():
                raise ContractError('criterion requirement missing')
        else:
            r_id=c.get('requirement_id')
            if not isinstance(r_id,str) or r_id not in expected:
                raise ContractError('criterion references missing requirement')
            covered.add(r_id)
        p=c.get('probe')
        if not isinstance(p,dict) or not isinstance(p.get('type'),str) or p['type'] not in TYPES:
            raise ContractError('invalid probe')
        if p['type']!='manual' and (not isinstance(p.get('path'),str) or not p['path']):
            raise ContractError('path is required')
        if p['type']=='sha256' and (not isinstance(p.get('expected_sha256'),str) or not re.fullmatch('[0-9a-fA-F]{64}',p['expected_sha256'])):
            raise ContractError('expected_sha256 must be 64 hex chars')
    if version == 2 and covered != set(expected):
        raise ContractError('unmapped requirements: ' + ', '.join(sorted(set(expected)-covered)))
    return version, expected


def evaluate(root, contract):
    root=Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ContractError('review root is not directory')
    version, requirements=validate_contract(contract)
    findings=[]
    for c in contract['criteria']:
        p=c['probe']
        try:
            status,reason,digest=run_probe(root,p)
        except (ContractError,FileNotFoundError,UnicodeDecodeError,OSError) as ex:
            status,reason,digest='FAIL',str(ex),None
        findings.append({'id':c['id'], 'requirement_id':c.get('requirement_id',c['id']),
                         'requirement':requirements.get(c.get('requirement_id'),c.get('requirement')),
                         'probe_type':p['type'], 'path':p.get('path'),
                         'status':status,'detail':reason,'observed_sha256':digest})
    statuses=[f['status'] for f in findings]
    outcome='BLOCKED' if 'FAIL' in statuses else ('INCOMPLETE' if 'NOT_VERIFIED' in statuses else 'EVIDENCE_CHECKS_PASS')
    mapping={}
    for f in findings:
        mapping.setdefault(f['requirement_id'],[]).append(f['status'])
    coverage={k: ('FAIL' if 'FAIL' in v else 'NOT_VERIFIED' if 'NOT_VERIFIED' in v else 'STATIC_PROBES_PASS') for k,v in mapping.items()}
    snapshot=hashlib.sha256(json.dumps({'contract':contract,'findings':findings},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return {'schema_version':version,'review_root':str(root),'review_outcome':outcome,
            'release_approved':False, 'requirements_source':contract.get('requirements_source'),
            'requirement_probe_coverage':coverage, 'findings':findings,
            'observed_probe_snapshot_sha256':snapshot,
            'limits':['Probe contract and original requirement source are NOT authenticated.',
                      'Only explicitly listed paths are observed; snapshot does not cover entire repository.',
                      'Static probes are narrow heuristics, NOT proof of function, accessibility or security.',
                      'No project tests, UI/hardware observation, release approval, or human identity verification.']}


def main(argv=None):
    ap=argparse.ArgumentParser(description='Nonexecuting, read-only independent STATIC review')
    ap.add_argument('--root',required=True,help='Artifact/repository root')
    ap.add_argument('--contract',required=True,help='JSON contract (max 1 MiB)')
    args=ap.parse_args(argv)
    try:
        path=Path(args.contract)
        if path.stat().st_size > MAX_CONTRACT:
            raise ContractError('contract too large')
        contract=json.loads(path.read_text(encoding='utf-8'))
        result=evaluate(Path(args.root),contract)
    except (ValueError,OSError) as ex:
        print(json.dumps({'error':str(ex),'review_outcome':'INVALID_CONTRACT'},ensure_ascii=False))
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return {'EVIDENCE_CHECKS_PASS':0,'BLOCKED':1,'INCOMPLETE':3}[result['review_outcome']]

if __name__=='__main__':
    raise SystemExit(main())
