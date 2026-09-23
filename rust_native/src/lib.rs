use std::borrow::Cow;

use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{
    PyAny, PyByteArray, PyByteArrayMethods, PyBytes, PyDict, PyDictMethods, PyInt, PyList,
    PyListMethods, PyString, PyTuple,
};
use serde_json::Value as SerdeValue;
use sonic_rs::{get_many_unchecked, JsonValueTrait, PointerNode, PointerTree};

#[derive(Clone)]
enum NativeNode {
    Null,
    Bool(bool),
    Number {
        value: serde_json::Number,
        raw: String,
    },
    String(String),
    Array(Vec<usize>),
    Object(Vec<(String, usize)>),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum NativeState {
    ExpectValue,
    ExpectKeyOrEnd,
    AfterKey,
    AfterValue,
    ExpectKey,
    ExpectArrayOrEnd,
    InString,
    InNumber,
    InLiteral,
    Done,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum StringMode {
    Key,
    Value,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ContainerKind {
    Object,
    Array,
}

struct NativeContext {
    kind: ContainerKind,
    node: usize,
}

struct NativeCore {
    arena: Vec<NativeNode>,
    parents: Vec<Option<usize>>,
    parent_array_indices: Vec<Option<usize>>,
    parent_object_keys: Vec<Option<String>>,
    dirty: Vec<bool>,
    dirty_children: Vec<Vec<usize>>,
    dirty_child_pending: Vec<bool>,
    root: Option<usize>,
    stack: Vec<NativeContext>,
    state: NativeState,
    current_key: Option<String>,
    string_mode: Option<StringMode>,
    string_buffer: String,
    string_node: Option<usize>,
    partial_string_attached: bool,
    pending_high_surrogate: Option<u16>,
    escape: bool,
    unicode_escape: bool,
    unicode_digits: String,
    number_buffer: String,
    literal_buffer: String,
    partial_scalar_node: Option<usize>,
    complete: bool,
    error: Option<String>,
    partial_string_materialized: bool,
}

impl NativeCore {
    fn new() -> Self {
        Self {
            arena: Vec::new(),
            parents: Vec::new(),
            parent_array_indices: Vec::new(),
            parent_object_keys: Vec::new(),
            dirty: Vec::new(),
            dirty_children: Vec::new(),
            dirty_child_pending: Vec::new(),
            root: None,
            stack: Vec::new(),
            state: NativeState::ExpectValue,
            current_key: None,
            string_mode: None,
            string_buffer: String::new(),
            string_node: None,
            partial_string_attached: false,
            pending_high_surrogate: None,
            escape: false,
            unicode_escape: false,
            unicode_digits: String::new(),
            number_buffer: String::new(),
            literal_buffer: String::new(),
            partial_scalar_node: None,
            complete: false,
            error: None,
            partial_string_materialized: false,
        }
    }

    fn reset(&mut self) {
        *self = Self::new();
    }

    fn push_node(&mut self, node: NativeNode) -> usize {
        let id = self.arena.len();
        self.arena.push(node);
        self.parents.push(None);
        self.parent_array_indices.push(None);
        self.parent_object_keys.push(None);
        self.dirty.push(true);
        self.dirty_children.push(Vec::new());
        self.dirty_child_pending.push(false);
        id
    }

    fn mark_dirty(&mut self, node: usize) {
        // Propagate only the changed path so polling avoids rescanning stable siblings.
        self.dirty[node] = true;
        let mut current = Some(node);
        while let Some(id) = current {
            let Some(parent) = self.parents[id] else {
                break;
            };
            if !self.dirty_child_pending[id] {
                self.dirty_children[parent].push(id);
                self.dirty_child_pending[id] = true;
            }
            self.dirty[parent] = true;
            current = Some(parent);
        }
    }

    fn consume(&mut self, chunk: &str) {
        if self.error.is_some() {
            return;
        }
        if self.complete {
            if chunk
                .chars()
                .any(|ch| !matches!(ch, ' ' | '\n' | '\r' | '\t'))
            {
                self.error = Some("extra trailing data after complete document".to_string());
            }
            return;
        }
        let mut chars = chunk.char_indices().peekable();
        while let Some((index, ch)) = chars.next() {
            if self.state == NativeState::InString
                && self.string_mode.is_some()
                && !self.escape
                && !self.unicode_escape
                && self.pending_high_surrogate.is_none()
                && ch != '\\'
                && ch != '"'
                && ch >= ' '
            {
                let mut end = index + ch.len_utf8();
                while let Some(&(next_index, next_ch)) = chars.peek() {
                    if next_ch == '\\' || next_ch == '"' || next_ch < ' ' {
                        break;
                    }
                    chars.next();
                    end = next_index + next_ch.len_utf8();
                }
                self.string_buffer.push_str(&chunk[index..end]);
                continue;
            }
            self.consume_char(ch);
            if self.error.is_some() {
                return;
            }
        }
    }

    fn consume_ascii(&mut self, chunk: &[u8]) {
        if self.error.is_some() {
            return;
        }
        if self.complete {
            if chunk
                .iter()
                .any(|byte| !matches!(*byte, b' ' | b'\n' | b'\r' | b'\t'))
            {
                self.error = Some("extra trailing data after complete document".to_string());
            }
            return;
        }
        let mut index = 0;
        while index < chunk.len() {
            if !matches!(
                self.state,
                NativeState::InString | NativeState::InNumber | NativeState::InLiteral
            ) && matches!(chunk[index], b' ' | b'\n' | b'\r' | b'\t')
            {
                while index < chunk.len() && matches!(chunk[index], b' ' | b'\n' | b'\r' | b'\t') {
                    index += 1;
                }
                continue;
            }
            if self.state == NativeState::InNumber {
                let start = index;
                while index < chunk.len()
                    && matches!(chunk[index], b'0'..=b'9' | b'+' | b'-' | b'.' | b'e' | b'E')
                {
                    index += 1;
                }
                if index > start {
                    self.number_buffer
                        .push_str(std::str::from_utf8(&chunk[start..index]).unwrap());
                    continue;
                }
            }
            if self.state == NativeState::InLiteral {
                let start = index;
                while index < chunk.len() && chunk[index].is_ascii_alphabetic() {
                    index += 1;
                }
                if index > start {
                    self.literal_buffer
                        .push_str(std::str::from_utf8(&chunk[start..index]).unwrap());
                    let token = self.literal_buffer.as_str();
                    if !["true", "false", "null"]
                        .iter()
                        .any(|literal| literal.starts_with(token))
                        || self.literal_buffer.len() > 5
                    {
                        self.error = Some(format!(
                            "invalid literal prefix {:?}",
                            &token[..token.len().min(16)]
                        ));
                        return;
                    }
                    continue;
                }
            }
            if self.state == NativeState::InString
                && self.string_mode.is_some()
                && !self.escape
                && !self.unicode_escape
                && self.pending_high_surrogate.is_none()
            {
                let start = index;
                while index < chunk.len()
                    && chunk[index] != b'\\'
                    && chunk[index] != b'"'
                    && chunk[index] >= 0x20
                {
                    index += 1;
                }
                if index > start {
                    // The fast path is only entered for ASCII input, so this
                    // slice is valid UTF-8 and can be appended in one step.
                    self.string_buffer
                        .push_str(std::str::from_utf8(&chunk[start..index]).unwrap());
                    continue;
                }
            }
            self.consume_char(chunk[index] as char);
            index += 1;
            if self.error.is_some() {
                return;
            }
        }
    }

    fn consume_char(&mut self, ch: char) {
        if self.state == NativeState::InString {
            self.consume_string_char(ch);
            return;
        }
        if self.state == NativeState::InNumber {
            if matches!(ch, '0'..='9' | '+' | '-' | '.' | 'e' | 'E') {
                self.number_buffer.push(ch);
                return;
            }
            self.finalize_number();
            if self.error.is_some() {
                return;
            }
            self.consume_nonstring_char(ch);
            return;
        }
        if self.state == NativeState::InLiteral {
            if ch.is_ascii_alphabetic() {
                self.literal_buffer.push(ch);
                let token = self.literal_buffer.as_str();
                if !["true", "false", "null"]
                    .iter()
                    .any(|literal| literal.starts_with(token))
                    || self.literal_buffer.len() > 5
                {
                    self.error = Some(format!(
                        "invalid literal prefix {:?}",
                        &token[..token.len().min(16)]
                    ));
                }
                return;
            }
            self.finalize_literal();
            if self.error.is_some() {
                return;
            }
            self.consume_nonstring_char(ch);
            return;
        }
        self.consume_nonstring_char(ch);
    }

    fn finish(&mut self) {
        if self.complete || self.error.is_some() {
            return;
        }
        match self.state {
            NativeState::InNumber => self.finalize_number(),
            NativeState::InLiteral => self.finalize_literal(),
            _ => {}
        }
        if self.error.is_some() || self.complete {
            return;
        }
        if self.root.is_some() && self.stack.is_empty() && self.state == NativeState::AfterValue {
            self.complete = true;
            self.state = NativeState::Done;
            return;
        }
        if self.root.is_none() && self.state == NativeState::ExpectValue {
            return;
        }
        self.error = Some("incomplete json document".to_string());
    }

    fn prepare_for_poll(&mut self) {
        if self.state != NativeState::InString
            || self.string_mode != Some(StringMode::Value)
            || self.partial_string_materialized
        {
            return;
        }
        let string_node = if let Some(node) = self.string_node {
            node
        } else {
            let node = self.push_node(NativeNode::String(self.string_buffer.clone()));
            self.string_node = Some(node);
            node
        };
        if let NativeNode::String(value) = &mut self.arena[string_node] {
            *value = self.string_buffer.clone();
        }
        if let Some(context) = self.stack.last() {
            let context_node = context.node;
            match context.kind {
                ContainerKind::Object => {
                    let Some(key) = self.current_key.clone() else {
                        return;
                    };
                    self.parent_object_keys[string_node] = Some(key.clone());
                    if let NativeNode::Object(fields) = &mut self.arena[context_node] {
                        if let Some((_, node)) = fields.iter_mut().find(|(field, _)| field == &key)
                        {
                            *node = string_node;
                        } else {
                            fields.push((key, string_node));
                        }
                    }
                }
                ContainerKind::Array => {
                    if !self.partial_string_attached {
                        if let NativeNode::Array(items) = &mut self.arena[context_node] {
                            self.parent_array_indices[string_node] = Some(items.len());
                            items.push(string_node);
                        }
                    }
                }
            }
            self.parents[string_node] = Some(context_node);
        } else if self.root.is_none() {
            self.root = Some(string_node);
        }
        self.partial_string_attached = true;
        self.partial_string_materialized = true;
        self.mark_dirty(string_node);
    }

    fn prepare_for_structural_poll(&mut self) {
        match self.state {
            NativeState::InNumber => {
                if let Ok(SerdeValue::Number(number)) =
                    serde_json::from_str::<SerdeValue>(&self.number_buffer)
                {
                    if number.as_f64().is_none_or(|value| value.is_finite()) {
                        self.materialize_partial_scalar(NativeNode::Number {
                            value: number,
                            raw: self.number_buffer.clone(),
                        });
                    }
                }
            }
            NativeState::InLiteral => {
                let node = match self.literal_buffer.as_str() {
                    "true" => Some(NativeNode::Bool(true)),
                    "false" => Some(NativeNode::Bool(false)),
                    "null" => Some(NativeNode::Null),
                    _ => None,
                };
                if let Some(node) = node {
                    self.materialize_partial_scalar(node);
                }
            }
            _ => {}
        }
    }

    fn materialize_partial_scalar(&mut self, node: NativeNode) {
        if let Some(id) = self.partial_scalar_node {
            self.arena[id] = node;
            if self
                .stack
                .last()
                .is_some_and(|context| context.kind == ContainerKind::Object)
            {
                self.current_key.take();
            }
            self.mark_dirty(id);
            return;
        }

        let id = self.push_node(node);
        if self.root.is_none() {
            self.root = Some(id);
        } else if let Some(context) = self.stack.last() {
            match context.kind {
                ContainerKind::Object => {
                    let Some(key) = self.current_key.clone() else {
                        self.error = Some("missing object key for partial value".to_string());
                        return;
                    };
                    self.parent_object_keys[id] = Some(key.clone());
                    if let NativeNode::Object(fields) = &mut self.arena[context.node] {
                        fields.push((key, id));
                    }
                }
                ContainerKind::Array => {
                    if let NativeNode::Array(items) = &mut self.arena[context.node] {
                        self.parent_array_indices[id] = Some(items.len());
                        items.push(id);
                    }
                }
            }
            self.parents[id] = Some(context.node);
        }
        self.partial_scalar_node = Some(id);
        self.mark_dirty(id);
    }

    fn consume_nonstring_char(&mut self, ch: char) {
        if matches!(ch, ' ' | '\n' | '\r' | '\t') {
            return;
        }
        if self.complete {
            self.error = Some(format!("extra trailing data starting with {:?}", ch));
            return;
        }
        match self.state {
            NativeState::ExpectValue => self.start_value(ch),
            NativeState::ExpectKeyOrEnd => match ch {
                '}' => self.close_container(ContainerKind::Object),
                '"' => self.begin_string(StringMode::Key),
                _ => self.error = Some(format!("expected object key or end, got {:?}", ch)),
            },
            NativeState::AfterKey => {
                if ch == ':' {
                    self.state = NativeState::ExpectValue;
                } else {
                    self.error = Some(format!("expected colon after key, got {:?}", ch));
                }
            }
            NativeState::AfterValue => {
                let Some(context) = self.stack.last() else {
                    self.complete = true;
                    self.error = Some(format!("extra trailing data starting with {:?}", ch));
                    return;
                };
                match context.kind {
                    ContainerKind::Object => match ch {
                        ',' => self.state = NativeState::ExpectKey,
                        '}' => self.close_container(ContainerKind::Object),
                        _ => {
                            self.error = Some(format!("expected comma or object end, got {:?}", ch))
                        }
                    },
                    ContainerKind::Array => match ch {
                        ',' => self.state = NativeState::ExpectValue,
                        ']' => self.close_container(ContainerKind::Array),
                        _ => {
                            self.error = Some(format!("expected comma or array end, got {:?}", ch))
                        }
                    },
                }
            }
            NativeState::ExpectKey => {
                if ch == '"' {
                    self.begin_string(StringMode::Key);
                } else {
                    self.error = Some(format!("expected object key, got {:?}", ch));
                }
            }
            NativeState::ExpectArrayOrEnd => {
                if ch == ']' {
                    self.close_container(ContainerKind::Array);
                } else {
                    self.state = NativeState::ExpectValue;
                    self.consume_nonstring_char(ch);
                }
            }
            _ => self.error = Some(format!("unexpected parser state {:?}", self.state)),
        }
    }

    fn start_value(&mut self, ch: char) {
        match ch {
            '{' => {
                let node = self.push_node(NativeNode::Object(Vec::new()));
                self.attach_value(node);
                if self.error.is_some() {
                    return;
                }
                self.stack.push(NativeContext {
                    kind: ContainerKind::Object,
                    node,
                });
                self.state = NativeState::ExpectKeyOrEnd;
            }
            '[' => {
                let node = self.push_node(NativeNode::Array(Vec::new()));
                self.attach_value(node);
                if self.error.is_some() {
                    return;
                }
                self.stack.push(NativeContext {
                    kind: ContainerKind::Array,
                    node,
                });
                self.state = NativeState::ExpectArrayOrEnd;
            }
            '"' => self.begin_string(StringMode::Value),
            '-' | '0'..='9' => {
                self.state = NativeState::InNumber;
                self.number_buffer.clear();
                self.partial_scalar_node = None;
                self.number_buffer.push(ch);
            }
            't' | 'f' | 'n' => {
                self.state = NativeState::InLiteral;
                self.literal_buffer.clear();
                self.partial_scalar_node = None;
                self.literal_buffer.push(ch);
            }
            _ => self.error = Some(format!("expected value, got {:?}", ch)),
        }
    }

    fn attach_value(&mut self, node: usize) {
        if self.root.is_none() {
            self.root = Some(node);
            if !matches!(
                self.arena[node],
                NativeNode::Object(_) | NativeNode::Array(_)
            ) {
                self.state = NativeState::AfterValue;
            }
            return;
        }
        let Some(context) = self.stack.last() else {
            self.error = Some("received extra top-level value".to_string());
            return;
        };
        let context_node = context.node;
        match context.kind {
            ContainerKind::Object => {
                let Some(key) = self.current_key.take() else {
                    self.error = Some("missing object key for value".to_string());
                    return;
                };
                if let NativeNode::Object(fields) = &mut self.arena[context_node] {
                    self.parent_object_keys[node] = Some(key.clone());
                    if let Some((_, existing)) = fields.iter_mut().find(|(field, _)| field == &key)
                    {
                        *existing = node;
                    } else {
                        fields.push((key, node));
                    }
                }
            }
            ContainerKind::Array => {
                if let NativeNode::Array(items) = &mut self.arena[context_node] {
                    self.parent_array_indices[node] = Some(items.len());
                    items.push(node);
                }
            }
        }
        self.parents[node] = Some(context_node);
        self.mark_dirty(node);
        self.state = NativeState::AfterValue;
    }

    fn begin_string(&mut self, mode: StringMode) {
        self.state = NativeState::InString;
        self.string_mode = Some(mode);
        self.string_buffer.clear();
        self.string_node = None;
        self.partial_string_attached = false;
        self.pending_high_surrogate = None;
        self.escape = false;
        self.unicode_escape = false;
        self.unicode_digits.clear();
        self.partial_string_materialized = false;
    }

    fn append_unicode_code_unit(&mut self, code_unit: u16) {
        if let Some(high_surrogate) = self.pending_high_surrogate.take() {
            if (0xdc00..=0xdfff).contains(&code_unit) {
                let scalar = 0x10000
                    + (((high_surrogate - 0xd800) as u32) << 10)
                    + (code_unit - 0xdc00) as u32;
                self.string_buffer
                    .push(char::from_u32(scalar).expect("valid surrogate pair"));
                return;
            }
            self.error = Some("invalid unicode surrogate pair".to_string());
            return;
        }
        if (0xd800..=0xdbff).contains(&code_unit) {
            self.pending_high_surrogate = Some(code_unit);
        } else if (0xdc00..=0xdfff).contains(&code_unit) {
            self.error = Some("invalid unicode surrogate pair".to_string());
        } else {
            self.string_buffer
                .push(char::from_u32(code_unit as u32).expect("valid unicode scalar"));
        }
    }

    fn consume_string_char(&mut self, ch: char) {
        if self.unicode_escape {
            if ch.is_ascii_hexdigit() {
                self.unicode_digits.push(ch);
                if self.unicode_digits.len() == 4 {
                    let code_unit = u16::from_str_radix(&self.unicode_digits, 16).unwrap();
                    self.append_unicode_code_unit(code_unit);
                    self.unicode_digits.clear();
                    self.unicode_escape = false;
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                return;
            }
            self.error = Some("invalid unicode escape".to_string());
            return;
        }
        if self.escape {
            match ch {
                'u' => {
                    self.unicode_escape = true;
                    self.unicode_digits.clear();
                }
                '"' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('"');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                '\\' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('\\');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                '/' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('/');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                'b' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('\u{0008}');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                'f' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('\u{000c}');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                'n' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('\n');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                'r' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('\r');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                't' => {
                    if self.pending_high_surrogate.is_some() {
                        self.error = Some("invalid unicode surrogate pair".to_string());
                        return;
                    }
                    self.string_buffer.push('\t');
                    self.escape = false;
                    self.partial_string_materialized = false;
                }
                _ => self.error = Some(format!("invalid escape {:?}", ch)),
            }
            return;
        }
        match ch {
            '\\' => self.escape = true,
            '"' => {
                if self.pending_high_surrogate.is_some() {
                    self.error = Some("invalid unicode surrogate pair".to_string());
                    return;
                }
                let node = if let Some(node) = self.string_node {
                    if let NativeNode::String(value) = &mut self.arena[node] {
                        *value = self.string_buffer.clone();
                    }
                    self.mark_dirty(node);
                    node
                } else {
                    self.push_node(NativeNode::String(self.string_buffer.clone()))
                };
                match self.string_mode {
                    Some(StringMode::Key) => {
                        self.current_key = Some(self.string_buffer.clone());
                        self.state = NativeState::AfterKey;
                    }
                    Some(StringMode::Value) => {
                        if self.partial_string_attached {
                            if let Some(context) = self.stack.last() {
                                if context.kind == ContainerKind::Object {
                                    self.current_key.take();
                                }
                            }
                            self.state = NativeState::AfterValue;
                        } else {
                            self.attach_value(node);
                        }
                    }
                    None => self.error = Some("unexpected string state".to_string()),
                }
                self.string_mode = None;
                self.string_buffer.clear();
                self.string_node = None;
                self.partial_string_attached = false;
                self.partial_string_materialized = false;
            }
            _ if (ch as u32) < 0x20 => {
                self.error = Some("invalid control character in string".to_string())
            }
            _ => {
                if self.pending_high_surrogate.is_some() {
                    self.error = Some("invalid unicode surrogate pair".to_string());
                    return;
                }
                self.string_buffer.push(ch);
                self.partial_string_materialized = false;
            }
        }
    }

    fn finalize_number(&mut self) {
        let token = std::mem::take(&mut self.number_buffer);
        let parsed = serde_json::from_str::<SerdeValue>(&token);
        self.state = NativeState::AfterValue;
        let Ok(SerdeValue::Number(number)) = parsed else {
            self.error = Some(format!("invalid number {:?}", token));
            return;
        };
        if number.as_f64().is_some_and(|value| !value.is_finite()) {
            self.error = Some("non-finite JSON number".to_string());
            return;
        }
        let number_node = NativeNode::Number {
            value: number,
            raw: token,
        };
        if let Some(node) = self.partial_scalar_node.take() {
            self.arena[node] = number_node;
            if self
                .stack
                .last()
                .is_some_and(|context| context.kind == ContainerKind::Object)
            {
                self.current_key.take();
            }
            self.mark_dirty(node);
        } else {
            let node = self.push_node(number_node);
            self.attach_value(node);
        }
    }

    fn finalize_literal(&mut self) {
        let token = std::mem::take(&mut self.literal_buffer);
        self.state = NativeState::AfterValue;
        let node = match token.as_str() {
            "true" => NativeNode::Bool(true),
            "false" => NativeNode::Bool(false),
            "null" => NativeNode::Null,
            _ => {
                self.error = Some(format!("invalid literal {:?}", token));
                return;
            }
        };
        if let Some(partial_node) = self.partial_scalar_node.take() {
            self.arena[partial_node] = node;
            if self
                .stack
                .last()
                .is_some_and(|context| context.kind == ContainerKind::Object)
            {
                self.current_key.take();
            }
            self.mark_dirty(partial_node);
        } else {
            let node = self.push_node(node);
            self.attach_value(node);
        }
    }

    fn close_container(&mut self, expected: ContainerKind) {
        let Some(context) = self.stack.pop() else {
            self.error = Some("unexpected closing token".to_string());
            return;
        };
        if context.kind != expected {
            self.error = Some("mismatched close".to_string());
            return;
        }
        if self.stack.is_empty() {
            self.complete = true;
            self.state = NativeState::Done;
        } else {
            self.state = NativeState::AfterValue;
        }
    }
}

fn python_float_from_raw(py: Python<'_>, raw: &str) -> PyResult<Py<PyAny>> {
    let raw = PyString::new(py, raw);
    let ptr = unsafe { pyo3::ffi::PyFloat_FromString(raw.as_ptr()) };
    let value = unsafe { Bound::<PyAny>::from_owned_ptr_or_err(py, ptr)? }.unbind();
    if !value.bind(py).extract::<f64>()?.is_finite() {
        return Err(PyValueError::new_err("non-finite JSON number"));
    }
    Ok(value)
}

fn python_int_from_raw(py: Python<'_>, raw: &str) -> PyResult<Py<PyAny>> {
    py.import("builtins")?
        .getattr("int")?
        .call1((raw,))
        .map(|value| value.unbind())
}

fn python_number_from_raw(
    py: Python<'_>,
    value: &serde_json::Number,
    raw: &str,
) -> PyResult<Py<PyAny>> {
    if raw.bytes().any(|byte| matches!(byte, b'.' | b'e' | b'E')) {
        return python_float_from_raw(py, raw);
    }
    if let Some(integer) = value.as_i64() {
        return Ok(integer.into_pyobject(py)?.unbind().into());
    }
    if let Some(integer) = value.as_u64() {
        return Ok(integer.into_pyobject(py)?.unbind().into());
    }
    python_int_from_raw(py, raw)
}

fn native_scalar_to_python(py: Python<'_>, node: &NativeNode) -> PyResult<Py<PyAny>> {
    match node {
        NativeNode::Null => Ok(py.None()),
        NativeNode::Bool(value) => Ok(pyo3::types::PyBool::new(py, *value)
            .to_owned()
            .unbind()
            .into()),
        NativeNode::Number { value, raw } => python_number_from_raw(py, value, raw),
        NativeNode::String(value) => Ok(value.clone().into_pyobject(py)?.unbind().into()),
        NativeNode::Array(_) | NativeNode::Object(_) => {
            Err(PyTypeError::new_err("expected scalar native node"))
        }
    }
}

#[pyclass(module = "streaming_json_parser_native")]
struct ParseResult {
    status: Py<PyAny>,
    value: Py<PyAny>,
    complete: bool,
    error: Option<Py<PyAny>>,
}

type NativeSnapshot = (&'static str, Py<PyAny>, Option<Py<PyAny>>);

#[pymethods]
impl ParseResult {
    #[new]
    #[pyo3(signature = (status, value, complete, error=None))]
    fn new(status: Py<PyAny>, value: Py<PyAny>, complete: bool, error: Option<Py<PyAny>>) -> Self {
        Self {
            status,
            value,
            complete,
            error,
        }
    }

    #[getter]
    fn status<'py>(&self, py: Python<'py>) -> Py<PyAny> {
        self.status.clone_ref(py)
    }

    #[getter]
    fn value<'py>(&self, py: Python<'py>) -> Py<PyAny> {
        self.value.clone_ref(py)
    }

    #[getter]
    fn complete(&self) -> bool {
        self.complete
    }

    #[getter]
    fn error<'py>(&self, py: Python<'py>) -> Py<PyAny> {
        self.error
            .as_ref()
            .map(|value| value.clone_ref(py))
            .unwrap_or_else(|| py.None())
    }
}

#[pyclass]
struct IncrementalJsonParser {
    core: NativeCore,
    pending_utf8: Vec<u8>,
    snapshot_cache: Vec<Option<Py<PyAny>>>,
    finished: bool,
    fast_value: Option<Py<PyAny>>,
    fast_error: Option<String>,
    status_empty: Option<Py<PyAny>>,
    status_partial: Option<Py<PyAny>>,
    status_complete: Option<Py<PyAny>>,
    status_invalid: Option<Py<PyAny>>,
    public_api: bool,
    public_materialize_partial_string: bool,
    public_materialize_partial_scalar: bool,
}

impl IncrementalJsonParser {
    fn consume_and_poll_result_mode<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_result_with_copy(
            py,
            materialize_partial_string,
            materialize_partial_scalar,
            copy_value,
        )
    }

    fn finish_result_mode<'py>(
        &mut self,
        py: Python<'py>,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        self.poll_result_with_copy(
            py,
            materialize_partial_string,
            materialize_partial_scalar,
            copy_value,
        )
    }

    fn cache_value(&mut self, py: Python<'_>, id: usize, value: Py<PyAny>) -> Py<PyAny> {
        if self.snapshot_cache.len() <= id {
            self.snapshot_cache.resize_with(id + 1, || None);
        }
        self.snapshot_cache[id] = Some(value.clone_ref(py));
        self.core.dirty[id] = false;
        value
    }

    fn sync_array(
        &mut self,
        py: Python<'_>,
        id: usize,
        cached: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let (list, had_cache) = if let Some(value) = cached {
            (value.bind(py).cast::<PyList>()?.clone(), true)
        } else {
            let value: Py<PyAny> = PyList::empty(py).unbind().into();
            if self.snapshot_cache.len() <= id {
                self.snapshot_cache.resize_with(id + 1, || None);
            }
            self.snapshot_cache[id] = Some(value.clone_ref(py));
            (value.bind(py).cast::<PyList>()?.clone(), false)
        };

        if had_cache {
            let dirty_children = std::mem::take(&mut self.core.dirty_children[id]);
            for child in dirty_children {
                self.core.dirty_child_pending[child] = false;
                let Some(index) = self.core.parent_array_indices[child] else {
                    continue;
                };
                let item_count = match &self.core.arena[id] {
                    NativeNode::Array(items) => items.len(),
                    _ => 0,
                };
                if index >= item_count {
                    continue;
                }
                let value = self.sync_node(py, child)?;
                if index < list.len() {
                    list.set_item(index, value)?;
                } else {
                    list.append(value)?;
                }
            }
            while list.len()
                < match &self.core.arena[id] {
                    NativeNode::Array(items) => items.len(),
                    _ => 0,
                }
            {
                let index = list.len();
                let child = match &self.core.arena[id] {
                    NativeNode::Array(items) => items[index],
                    _ => unreachable!(),
                };
                let value = self.sync_node(py, child)?;
                list.append(value)?;
            }
        } else {
            let dirty_children = std::mem::take(&mut self.core.dirty_children[id]);
            for child in dirty_children {
                self.core.dirty_child_pending[child] = false;
            }
            let items = match &self.core.arena[id] {
                NativeNode::Array(items) => items.clone(),
                _ => Vec::new(),
            };
            for (index, item) in items.into_iter().enumerate() {
                let value = self.sync_node(py, item)?;
                if index < list.len() {
                    list.set_item(index, value)?;
                } else {
                    list.append(value)?;
                }
            }
        }
        Ok(self.cache_value(py, id, list.clone().unbind().into()))
    }

    fn sync_object(
        &mut self,
        py: Python<'_>,
        id: usize,
        cached: Option<Py<PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let (dict, had_cache) = if let Some(value) = cached {
            (value.bind(py).cast::<PyDict>()?.clone(), true)
        } else {
            let value: Py<PyAny> = PyDict::new(py).unbind().into();
            if self.snapshot_cache.len() <= id {
                self.snapshot_cache.resize_with(id + 1, || None);
            }
            self.snapshot_cache[id] = Some(value.clone_ref(py));
            (value.bind(py).cast::<PyDict>()?.clone(), false)
        };

        if had_cache {
            let dirty_children = std::mem::take(&mut self.core.dirty_children[id]);
            for child in dirty_children {
                self.core.dirty_child_pending[child] = false;
                let Some(key) = self.core.parent_object_keys[child].clone() else {
                    continue;
                };
                dict.set_item(key, self.sync_node(py, child)?)?;
            }
        } else {
            let dirty_children = std::mem::take(&mut self.core.dirty_children[id]);
            for child in dirty_children {
                self.core.dirty_child_pending[child] = false;
            }
            let fields = match &self.core.arena[id] {
                NativeNode::Object(fields) => fields.clone(),
                _ => Vec::new(),
            };
            for (key, item) in fields {
                dict.set_item(key, self.sync_node(py, item)?)?;
            }
        }
        Ok(self.cache_value(py, id, dict.clone().unbind().into()))
    }

    fn sync_node(&mut self, py: Python<'_>, id: usize) -> PyResult<Py<PyAny>> {
        let cached = self
            .snapshot_cache
            .get(id)
            .and_then(|value| value.as_ref())
            .map(|value| value.clone_ref(py));
        if !self.core.dirty[id] {
            if let Some(value) = cached {
                return Ok(value);
            }
        }

        match &self.core.arena[id] {
            NativeNode::Null
            | NativeNode::Bool(_)
            | NativeNode::Number { .. }
            | NativeNode::String(_) => {
                let value = native_scalar_to_python(py, &self.core.arena[id])?;
                Ok(self.cache_value(py, id, value))
            }
            NativeNode::Array(_) => self.sync_array(py, id, cached),
            NativeNode::Object(_) => self.sync_object(py, id, cached),
        }
    }

    fn feed_bytes(&mut self, bytes: &[u8]) {
        if self.core.error.is_some() {
            return;
        }
        if self.pending_utf8.is_empty() {
            if bytes.is_ascii() {
                self.core.consume_ascii(bytes);
                return;
            }
            if let Ok(text) = std::str::from_utf8(bytes) {
                self.core.consume(text);
                return;
            }
        }
        self.pending_utf8.extend_from_slice(bytes);
        let input = std::mem::take(&mut self.pending_utf8);
        if input.is_ascii() {
            self.core.consume_ascii(&input);
            return;
        }
        match std::str::from_utf8(&input) {
            Ok(text) => self.core.consume(text),
            Err(error) => {
                let valid_up_to = error.valid_up_to();
                if error.error_len().is_none() {
                    self.core
                        .consume(std::str::from_utf8(&input[..valid_up_to]).unwrap());
                    self.pending_utf8.extend_from_slice(&input[valid_up_to..]);
                } else {
                    self.core.error = Some(format!("invalid utf-8 at byte {valid_up_to}"));
                }
            }
        }
    }

    fn status_value<'py>(&self, py: Python<'py>, status: &'static str) -> PyResult<Py<PyAny>> {
        let configured = match status {
            "empty" => self.status_empty.as_ref(),
            "partial" => self.status_partial.as_ref(),
            "complete" => self.status_complete.as_ref(),
            "invalid" => self.status_invalid.as_ref(),
            _ => None,
        };
        if let Some(value) = configured {
            return Ok(value.clone_ref(py));
        }
        Ok(status.into_pyobject(py)?.unbind().into())
    }

    fn snapshot<'py>(
        &mut self,
        py: Python<'py>,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
    ) -> PyResult<NativeSnapshot> {
        if let Some(value) = self.fast_value.as_ref() {
            let error = self
                .fast_error
                .as_ref()
                .map(|error| {
                    error
                        .clone()
                        .into_pyobject(py)
                        .map(|value| value.unbind().into())
                })
                .transpose()?;
            return Ok((
                if self.fast_error.is_some() {
                    "invalid"
                } else {
                    "complete"
                },
                value.clone_ref(py),
                error,
            ));
        }
        if let Some(error) = self.fast_error.as_ref() {
            return Ok((
                "invalid",
                py.None(),
                Some(error.clone().into_pyobject(py)?.unbind().into()),
            ));
        }
        if materialize_partial_string {
            self.core.prepare_for_poll();
        }
        if materialize_partial_scalar {
            self.core.prepare_for_structural_poll();
        }
        let status = if self.core.error.is_some() {
            "invalid"
        } else if self.core.complete {
            "complete"
        } else if self.core.root.is_some() || self.core.state != NativeState::ExpectValue {
            "partial"
        } else {
            "empty"
        };
        let value = match self.core.root {
            Some(root) => self.sync_node(py, root)?,
            None => py.None(),
        };
        let error = match &self.core.error {
            Some(error) => Some(error.clone().into_pyobject(py)?.unbind().into()),
            None => None,
        };
        Ok((status, value, error))
    }

    fn poll_tuple<'py>(
        &mut self,
        py: Python<'py>,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
    ) -> PyResult<Py<PyAny>> {
        let (status, value, error) =
            self.snapshot(py, materialize_partial_string, materialize_partial_scalar)?;
        let status = status.into_pyobject(py)?.unbind().into();
        let error: Py<PyAny> = error.unwrap_or_else(|| py.None());
        Ok(PyTuple::new(py, [status, value, error])?.unbind().into())
    }

    fn poll_result<'py>(
        &mut self,
        py: Python<'py>,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
    ) -> PyResult<Py<PyAny>> {
        self.poll_result_with_copy(
            py,
            materialize_partial_string,
            materialize_partial_scalar,
            false,
        )
    }

    fn poll_result_with_copy<'py>(
        &mut self,
        py: Python<'py>,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        let (status, value, error) =
            self.snapshot(py, materialize_partial_string, materialize_partial_scalar)?;
        let value = if copy_value {
            let copy = py.import("copy")?;
            copy.getattr("deepcopy")?.call1((value.bind(py),))?.unbind()
        } else {
            value
        };
        let result = ParseResult {
            status: self.status_value(py, status)?,
            value,
            complete: status == "complete",
            error,
        };
        Ok(Py::new(py, result)?.into())
    }
}

#[pyclass]
struct FacadeIncrementalJsonParser {
    inner: IncrementalJsonParser,
    materialize_partial_string: bool,
    materialize_partial_scalar: bool,
}

impl IncrementalJsonParser {
    fn can_try_complete_fast_path(&self) -> bool {
        self.core.error.is_none()
            && self.core.root.is_none()
            && self.core.state == NativeState::ExpectValue
            && self.pending_utf8.is_empty()
            && !self.finished
    }
}

fn data_has_non_whitespace(data: &Bound<'_, PyAny>) -> PyResult<bool> {
    if let Ok(bytes) = data.cast::<PyBytes>() {
        return Ok(bytes
            .as_bytes()
            .iter()
            .any(|byte| !is_json_whitespace(*byte)));
    }
    if let Ok(bytes) = data.cast::<PyByteArray>() {
        // No Python API is called while this borrowed slice is inspected.
        let bytes = unsafe { bytes.as_bytes() };
        return Ok(bytes.iter().any(|byte| !is_json_whitespace(*byte)));
    }
    if let Ok(text) = data.cast::<PyString>() {
        return Ok(text
            .to_str()?
            .as_bytes()
            .iter()
            .any(|byte| !is_json_whitespace(*byte)));
    }
    Err(PyTypeError::new_err("data must be bytes or str"))
}

fn try_complete_fast_path<'py>(
    py: Python<'py>,
    data: &Bound<'_, PyAny>,
) -> PyResult<Option<Py<PyAny>>> {
    if let Ok(bytes) = data.cast::<PyBytes>() {
        return decode_complete_fast_bytes(py, bytes.as_bytes());
    }
    if let Ok(text) = data.cast::<PyString>() {
        return decode_complete_fast_bytes(py, text.to_str()?.as_bytes());
    }
    if let Ok(bytes) = data.cast::<PyByteArray>() {
        // Materialize the Python result while the borrowed view is in scope;
        // the result owns all strings and containers before this returns.
        let bytes = unsafe { bytes.as_bytes() };
        return decode_complete_fast_bytes(py, bytes);
    }
    Ok(None)
}

fn decode_complete_fast_bytes<'py>(py: Python<'py>, bytes: &[u8]) -> PyResult<Option<Py<PyAny>>> {
    if !has_closed_root_suffix_hint(bytes) {
        return Ok(None);
    }
    let value = match sonic_rs::from_slice::<sonic_rs::LazyValue<'_>>(bytes) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    match lazy_value_to_python(py, &value) {
        Ok(value) => Ok(Some(value)),
        Err(_) => Ok(None),
    }
}

fn decode_complete_lazy_bytes(py: Python<'_>, bytes: &[u8]) -> PyResult<Py<PyAny>> {
    let value = sonic_rs::from_slice::<sonic_rs::LazyValue<'_>>(bytes)
        .map_err(|err| PyValueError::new_err(format!("invalid json: {err}")))?;
    lazy_value_to_python(py, &value)
}

#[pymethods]
impl FacadeIncrementalJsonParser {
    #[new]
    fn new() -> Self {
        Self {
            inner: IncrementalJsonParser::new(),
            materialize_partial_string: true,
            materialize_partial_scalar: false,
        }
    }

    fn configure_statuses(
        &mut self,
        empty: &Bound<'_, PyAny>,
        partial: &Bound<'_, PyAny>,
        complete: &Bound<'_, PyAny>,
        invalid: &Bound<'_, PyAny>,
    ) {
        self.inner
            .configure_statuses(empty, partial, complete, invalid);
    }

    fn configure_partial_mode(
        &mut self,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
    ) {
        self.materialize_partial_string = materialize_partial_string;
        self.materialize_partial_scalar = materialize_partial_scalar;
    }

    fn consume(&mut self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        self.inner.consume(py, data)
    }

    #[pyo3(signature = (data, copy_value=false))]
    fn feed<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        if self.materialize_partial_string && !self.materialize_partial_scalar {
            return self.inner.consume_and_poll_result(py, data, copy_value);
        }
        self.inner.consume_and_poll_result_mode(
            py,
            data,
            self.materialize_partial_string,
            self.materialize_partial_scalar,
            copy_value,
        )
    }

    #[pyo3(signature = (copy_value=false))]
    fn poll<'py>(&mut self, py: Python<'py>, copy_value: bool) -> PyResult<Py<PyAny>> {
        if self.materialize_partial_string && !self.materialize_partial_scalar {
            return self.inner.poll_result_value(py, copy_value);
        }
        self.inner.poll_result_with_copy(
            py,
            self.materialize_partial_string,
            self.materialize_partial_scalar,
            copy_value,
        )
    }

    #[pyo3(signature = (copy_value=false))]
    fn finish<'py>(&mut self, py: Python<'py>, copy_value: bool) -> PyResult<Py<PyAny>> {
        if self.materialize_partial_string && !self.materialize_partial_scalar {
            return self.inner.finish_result(py, copy_value);
        }
        self.inner.finish_result_mode(
            py,
            self.materialize_partial_string,
            self.materialize_partial_scalar,
            copy_value,
        )
    }

    fn reset(&mut self) {
        self.inner.reset();
    }

    #[pyo3(signature = (copy_value=false, max_items=None))]
    fn poll_many<'py>(
        &mut self,
        py: Python<'py>,
        copy_value: bool,
        max_items: Option<usize>,
    ) -> PyResult<Py<PyAny>> {
        let _ = max_items;
        let (status, value, _error) = self.inner.snapshot(
            py,
            self.materialize_partial_string,
            self.materialize_partial_scalar,
        )?;
        if status != "complete" {
            return Ok(PyList::empty(py).unbind().into());
        }
        let value = if copy_value {
            let copy = py.import("copy")?;
            copy.getattr("deepcopy")?.call1((value.bind(py),))?.unbind()
        } else {
            value
        };
        Ok(PyList::new(py, [value])?.unbind().into())
    }

    #[getter(_simple_string_state)]
    fn simple_string_state<'py>(&self, py: Python<'py>) -> Py<PyAny> {
        py.None()
    }
}

#[pymethods]
impl IncrementalJsonParser {
    #[new]
    fn new() -> Self {
        Self {
            core: NativeCore::new(),
            pending_utf8: Vec::new(),
            snapshot_cache: Vec::new(),
            finished: false,
            fast_value: None,
            fast_error: None,
            status_empty: None,
            status_partial: None,
            status_complete: None,
            status_invalid: None,
            public_api: false,
            public_materialize_partial_string: true,
            public_materialize_partial_scalar: false,
        }
    }

    fn configure_statuses(
        &mut self,
        empty: &Bound<'_, PyAny>,
        partial: &Bound<'_, PyAny>,
        complete: &Bound<'_, PyAny>,
        invalid: &Bound<'_, PyAny>,
    ) {
        self.status_empty = Some(empty.clone().unbind());
        self.status_partial = Some(partial.clone().unbind());
        self.status_complete = Some(complete.clone().unbind());
        self.status_invalid = Some(invalid.clone().unbind());
    }

    #[pyo3(signature = (materialize_partial_string=true, materialize_partial_scalar=false))]
    fn configure_public_api(
        &mut self,
        materialize_partial_string: bool,
        materialize_partial_scalar: bool,
    ) {
        self.public_api = true;
        self.public_materialize_partial_string = materialize_partial_string;
        self.public_materialize_partial_scalar = materialize_partial_scalar;
    }

    fn consume(&mut self, py: Python<'_>, data: &Bound<'_, PyAny>) -> PyResult<()> {
        if self.finished {
            return Err(pyo3::exceptions::PyRuntimeError::new_err(
                "parser is finished; call reset() before consuming more data",
            ));
        }
        if self.fast_error.is_some() {
            return Ok(());
        }
        if self.fast_value.is_some() {
            if data_has_non_whitespace(data)? {
                self.fast_error = Some("extra trailing data after complete document".to_string());
            }
            return Ok(());
        }
        if self.can_try_complete_fast_path() {
            if let Some(value) = try_complete_fast_path(py, data)? {
                self.fast_value = Some(value);
                return Ok(());
            }
        }
        if let Ok(bytes) = data.cast::<PyBytes>() {
            self.feed_bytes(bytes.as_bytes());
            return Ok(());
        }
        if let Ok(bytes) = data.cast::<PyByteArray>() {
            // The parser does not call back into Python while this borrowed
            // slice is used, so avoid copying every bytearray chunk.
            let bytes = unsafe { bytes.as_bytes() };
            self.feed_bytes(bytes);
            return Ok(());
        }
        if let Ok(text) = data.cast::<PyString>() {
            let text = text.to_str()?;
            if text.is_ascii() {
                self.core.consume_ascii(text.as_bytes());
            } else {
                self.core.consume(text.as_ref());
            }
            return Ok(());
        }
        Err(PyTypeError::new_err("data must be bytes or str"))
    }

    fn consume_and_poll<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_tuple(py, true, false)
    }

    fn consume_and_poll_structural<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_tuple(py, false, true)
    }

    fn consume_and_poll_partial<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_tuple(py, true, true)
    }

    #[pyo3(signature = (data, copy_value=false))]
    fn feed<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        if self.public_materialize_partial_string && !self.public_materialize_partial_scalar {
            return self.consume_and_poll_result(py, data, copy_value);
        }
        self.consume(py, data)?;
        self.poll_result_with_copy(
            py,
            self.public_materialize_partial_string,
            self.public_materialize_partial_scalar,
            copy_value,
        )
    }

    #[pyo3(signature = (data, copy_value=false))]
    fn consume_and_poll_result<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_result_with_copy(py, true, false, copy_value)
    }

    #[pyo3(signature = (data, copy_value=false))]
    fn consume_and_poll_structural_result<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_result_with_copy(py, false, true, copy_value)
    }

    #[pyo3(signature = (data, copy_value=false))]
    fn consume_and_poll_partial_result<'py>(
        &mut self,
        py: Python<'py>,
        data: &Bound<'_, PyAny>,
        copy_value: bool,
    ) -> PyResult<Py<PyAny>> {
        self.consume(py, data)?;
        self.poll_result_with_copy(py, true, true, copy_value)
    }

    #[pyo3(signature = (copy_value=false))]
    fn poll<'py>(&mut self, py: Python<'py>, copy_value: bool) -> PyResult<Py<PyAny>> {
        if self.public_api
            && self.public_materialize_partial_string
            && !self.public_materialize_partial_scalar
        {
            return self.poll_result_value(py, copy_value);
        }
        if self.public_api {
            return self.poll_result_with_copy(
                py,
                self.public_materialize_partial_string,
                self.public_materialize_partial_scalar,
                copy_value,
            );
        }
        self.poll_tuple(py, true, false)
    }

    fn poll_structural<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.poll_tuple(py, false, true)
    }

    fn poll_partial<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.poll_tuple(py, true, true)
    }

    #[pyo3(signature = (copy_value=false))]
    fn poll_result_value<'py>(&mut self, py: Python<'py>, copy_value: bool) -> PyResult<Py<PyAny>> {
        self.poll_result_with_copy(py, true, false, copy_value)
    }

    fn poll_structural_result<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.poll_result(py, false, true)
    }

    fn poll_partial_result<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.poll_result(py, true, true)
    }

    #[pyo3(signature = (copy_value=false, max_items=None))]
    fn poll_many<'py>(
        &mut self,
        py: Python<'py>,
        copy_value: bool,
        max_items: Option<usize>,
    ) -> PyResult<Py<PyAny>> {
        if max_items == Some(0) {
            return Ok(PyList::empty(py).unbind().into());
        }
        let (status, value, _error) = self.snapshot(
            py,
            self.public_materialize_partial_string,
            self.public_materialize_partial_scalar,
        )?;
        if status != "complete" {
            return Ok(PyList::empty(py).unbind().into());
        }
        let value = if copy_value {
            let copy = py.import("copy")?;
            copy.getattr("deepcopy")?.call1((value.bind(py),))?.unbind()
        } else {
            value
        };
        Ok(PyList::new(py, [value])?.unbind().into())
    }

    #[pyo3(signature = (copy_value=false))]
    fn finish<'py>(&mut self, py: Python<'py>, copy_value: bool) -> PyResult<Py<PyAny>> {
        if self.public_api
            && self.public_materialize_partial_string
            && !self.public_materialize_partial_scalar
        {
            return self.finish_result(py, copy_value);
        }
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        if self.public_api {
            return self.poll_result_with_copy(
                py,
                self.public_materialize_partial_string,
                self.public_materialize_partial_scalar,
                copy_value,
            );
        }
        self.poll_tuple(py, true, false)
    }

    fn finish_structural<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        self.poll_tuple(py, false, true)
    }

    fn finish_partial<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        self.poll_tuple(py, true, true)
    }

    #[pyo3(signature = (copy_value=false))]
    fn finish_result<'py>(&mut self, py: Python<'py>, copy_value: bool) -> PyResult<Py<PyAny>> {
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        self.poll_result_with_copy(py, true, false, copy_value)
    }

    fn finish_structural_result<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        self.poll_result(py, false, true)
    }

    fn finish_partial_result<'py>(&mut self, py: Python<'py>) -> PyResult<Py<PyAny>> {
        self.finished = true;
        if !self.pending_utf8.is_empty() {
            self.pending_utf8.clear();
            self.core.error = Some("invalid utf-8 at end of input".to_string());
        }
        self.core.finish();
        self.poll_result(py, true, true)
    }

    fn reset(&mut self) {
        self.core.reset();
        self.pending_utf8.clear();
        self.snapshot_cache.clear();
        self.finished = false;
        self.fast_value = None;
        self.fast_error = None;
    }

    #[getter(_simple_string_state)]
    fn simple_string_state<'py>(&self, py: Python<'py>) -> Py<PyAny> {
        py.None()
    }

    #[getter(_public_api)]
    fn public_api(&self) -> bool {
        self.public_api
    }
}

fn parse_paths(paths: &Bound<'_, PyTuple>) -> PyResult<Vec<Vec<PointerNode>>> {
    let mut out = Vec::with_capacity(paths.len());
    for item in paths.iter() {
        let tuple = item.cast::<PyTuple>()?;
        let mut path = Vec::with_capacity(tuple.len());
        for segment in tuple.iter() {
            if let Ok(key) = segment.cast::<PyString>() {
                path.push(PointerNode::from(key.to_str()?));
            } else if let Ok(index) = segment.cast::<PyInt>() {
                let idx: usize = index.extract()?;
                path.push(PointerNode::from(idx));
            } else {
                return Err(PyTypeError::new_err("path segments must be str or int"));
            }
        }
        out.push(path);
    }
    if out.is_empty() {
        return Err(PyValueError::new_err("at least one path is required"));
    }
    Ok(out)
}

fn lazy_value_to_python<'a>(
    py: Python<'_>,
    value: &sonic_rs::LazyValue<'a>,
) -> PyResult<Py<PyAny>> {
    let raw = value.as_raw_str();
    match raw.as_bytes().first().copied() {
        Some(b'n') => Ok(py.None()),
        Some(b't') => Ok(pyo3::types::PyBool::new(py, true)
            .to_owned()
            .unbind()
            .into()),
        Some(b'f') => Ok(pyo3::types::PyBool::new(py, false)
            .to_owned()
            .unbind()
            .into()),
        Some(b'"') => value
            .as_str()
            .ok_or_else(|| PyValueError::new_err("invalid string"))
            .and_then(|v| Ok(v.into_pyobject(py)?.unbind().into())),
        Some(b'[') => {
            let items: PyResult<Vec<Py<PyAny>>> = sonic_rs::to_array_iter(raw)
                .map(|item| {
                    let item =
                        item.map_err(|err| PyValueError::new_err(format!("invalid json: {err}")))?;
                    lazy_value_to_python(py, &item)
                })
                .collect();
            Ok(PyList::new(py, items?)?.unbind().into())
        }
        Some(b'{') => {
            let dict = PyDict::new(py);
            for entry in sonic_rs::to_object_iter(raw) {
                let (key, item) =
                    entry.map_err(|err| PyValueError::new_err(format!("invalid json: {err}")))?;
                dict.set_item(key.as_ref(), lazy_value_to_python(py, &item)?)?;
            }
            Ok(dict.unbind().into())
        }
        Some(b'-' | b'0'..=b'9') => {
            if raw.bytes().any(|byte| matches!(byte, b'.' | b'e' | b'E')) {
                return python_float_from_raw(py, raw);
            }
            if let Some(v) = value.as_i64() {
                return Ok(v.into_pyobject(py)?.unbind().into());
            }
            if let Some(v) = value.as_u64() {
                return Ok(v.into_pyobject(py)?.unbind().into());
            }
            python_int_from_raw(py, raw)
        }
        _ => Err(PyValueError::new_err("invalid json value")),
    }
}

#[pyfunction]
fn decode_complete<'py>(py: Python<'py>, data: &Bound<'py, PyAny>) -> PyResult<Py<PyAny>> {
    if let Ok(bytes) = data.cast::<PyBytes>() {
        return decode_complete_lazy_bytes(py, bytes.as_bytes());
    }
    if let Ok(bytes) = data.cast::<PyByteArray>() {
        let bytes = unsafe { bytes.as_bytes() };
        return decode_complete_lazy_bytes(py, bytes);
    }
    if let Ok(text) = data.cast::<PyString>() {
        return decode_complete_lazy_bytes(py, text.to_str()?.as_bytes());
    }
    Err(PyTypeError::new_err(
        "data must be bytes, bytearray, or str",
    ))
}

#[pyfunction]
fn decode_ndjson<'py>(py: Python<'py>, data: &Bound<'py, PyAny>) -> PyResult<Py<PyAny>> {
    let raw = if let Ok(bytes) = data.cast::<PyBytes>() {
        Cow::Borrowed(bytes.as_bytes())
    } else if let Ok(bytes) = data.cast::<PyByteArray>() {
        Cow::Owned(unsafe { bytes.as_bytes().to_vec() })
    } else if let Ok(text) = data.cast::<PyString>() {
        Cow::Borrowed(text.to_str()?.as_bytes())
    } else {
        return Err(PyTypeError::new_err(
            "data must be bytes, bytearray, or str",
        ));
    };

    let mut results = Vec::with_capacity(raw.iter().filter(|byte| **byte == b'\n').count());
    for line in raw.split(|byte| *byte == b'\n') {
        if line.is_empty() {
            continue;
        }
        let value = sonic_rs::from_slice::<sonic_rs::LazyValue<'_>>(line)
            .map_err(|err| PyValueError::new_err(format!("invalid json: {err}")))?;
        results.push(lazy_value_to_python(py, &value)?);
    }

    Ok(PyList::new(py, results)?.unbind().into())
}

fn is_json_whitespace(byte: u8) -> bool {
    matches!(byte, b' ' | b'\n' | b'\r' | b'\t')
}

fn has_closed_root_suffix_hint(payload: &[u8]) -> bool {
    let mut start = 0;
    while start < payload.len() && is_json_whitespace(payload[start]) {
        start += 1;
    }
    let mut end = payload.len();
    while end > start && is_json_whitespace(payload[end - 1]) {
        end -= 1;
    }
    if end - start < 2 {
        return false;
    }
    matches!(
        (payload[start], payload[end - 1]),
        (b'{', b'}') | (b'[', b']') | (b'"', b'"')
    )
}

fn has_complete_root_boundary(payload: &[u8]) -> bool {
    let mut index = 0;
    while index < payload.len() && is_json_whitespace(payload[index]) {
        index += 1;
    }
    if index == payload.len() {
        return false;
    }

    if payload[index] == b'"' {
        index += 1;
        let mut escaped = false;
        while index < payload.len() {
            let byte = payload[index];
            index += 1;
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                return payload[index..]
                    .iter()
                    .all(|byte| is_json_whitespace(*byte));
            }
        }
        return false;
    }

    let root_close = match payload[index] {
        b'{' => b'}',
        b'[' => b']',
        _ => return false,
    };
    let mut expected_closes = vec![root_close];
    index += 1;
    let mut escaped = false;
    let mut in_string = false;
    while index < payload.len() {
        let byte = payload[index];
        index += 1;
        if in_string {
            if escaped {
                escaped = false;
            } else if byte == b'\\' {
                escaped = true;
            } else if byte == b'"' {
                in_string = false;
            }
            continue;
        }
        if byte == b'"' {
            in_string = true;
        } else if byte == b'{' {
            expected_closes.push(b'}');
        } else if byte == b'[' {
            expected_closes.push(b']');
        } else if Some(&byte) == expected_closes.last() {
            expected_closes.pop();
            if expected_closes.is_empty() {
                return payload[index..]
                    .iter()
                    .all(|byte| is_json_whitespace(*byte));
            }
        } else if byte == b'}' || byte == b']' {
            return false;
        }
    }
    false
}

#[pyfunction]
fn is_complete_document(data: &Bound<'_, PyBytes>) -> bool {
    has_complete_root_boundary(data.as_bytes())
}

#[pyfunction]
fn extract_ndjson_paths<'py>(
    py: Python<'py>,
    data: &Bound<'py, PyAny>,
    paths: &Bound<'py, PyTuple>,
) -> PyResult<Py<PyAny>> {
    let raw = if let Ok(bytes) = data.cast::<PyBytes>() {
        Cow::Borrowed(bytes.as_bytes())
    } else if let Ok(bytes) = data.cast::<PyByteArray>() {
        // A mutable buffer cannot stay borrowed while Python result objects
        // are materialized, so copy it only for this detached-result API.
        let owned = unsafe { bytes.as_bytes().to_vec() };
        Cow::Owned(owned)
    } else if let Ok(s) = data.extract::<&str>() {
        Cow::Borrowed(s.as_bytes())
    } else {
        return Err(PyTypeError::new_err(
            "data must be bytes, bytearray, or str",
        ));
    };
    let parsed_paths = parse_paths(paths)?;
    let mut tree = PointerTree::new();
    for path in &parsed_paths {
        tree.add_path(path.iter());
    }

    let mut results: Vec<Py<PyAny>> =
        Vec::with_capacity(raw.iter().filter(|b| **b == b'\n').count());
    for line in raw.split(|b| *b == b'\n') {
        if line.is_empty() {
            continue;
        }
        let values = unsafe { get_many_unchecked(line, &tree) }
            .map_err(|err| PyValueError::new_err(format!("invalid json line: {err}")))?;

        let mut row = Vec::with_capacity(values.len());
        for value in values {
            match value {
                Some(lazy) => row.push(lazy_value_to_python(py, &lazy)?),
                None => row.push(py.None()),
            }
        }

        if parsed_paths.len() == 1 {
            results.push(row.into_iter().next().expect("row len checked"));
        } else {
            results.push(PyTuple::new(py, row)?.unbind().into());
        }
    }

    Ok(PyList::new(py, results)?.unbind().into())
}

#[pymodule]
fn streaming_json_parser_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(decode_complete, m)?)?;
    m.add_function(wrap_pyfunction!(decode_ndjson, m)?)?;
    m.add_function(wrap_pyfunction!(is_complete_document, m)?)?;
    m.add_function(wrap_pyfunction!(extract_ndjson_paths, m)?)?;
    m.add_class::<ParseResult>()?;
    m.add_class::<IncrementalJsonParser>()?;
    m.add_class::<FacadeIncrementalJsonParser>()?;
    Ok(())
}
