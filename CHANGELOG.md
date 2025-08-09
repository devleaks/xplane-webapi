# Changelog

All notable changes to this project will be documented in this file.

## 3.2.0 - 2025-08-09

Breaking change, `api.execute()` is now more explicitely `api.execute_command()`.

## 3.1.0 - 2025-07-31

Added callback to UDP dataref monitoring, like other rest and/or websocket API. Wow.

## 3.0.0 - 2025-07-07

Breaking change.

Datarefs of value type "data" are returned as *bytes*.
The API only performs BASE64 encode/decode with no further interpretation.

Convenience methods `get_string_value(encoding: str)` and `set_string_value(value: str, encoding: str)` are provided
to Dataref to get/set string values.
In all cases, string encoding need to be provided. There is no default encoding.

Note: It is possible to use python package `chardet` to guess encoding from bytes.

## 2.0.1 - 2025-06-15

Allows for multiple callback functions.
`set_callback` adds callback to list of callbacks, all called in turn.

In a next release, all handlers will be set of handlers.

## 2.0.0 - 2025-06-04

Refactor handlers.

## 1.2.O - 2025-06-03

Changed beacon callback prototype to pass beacon data and «same host» information in one call.

## 1.1.O - 2025-06-02

Using [natsort](https://github.com/SethMMorton/natsort/wiki) for version ordering as returned from X-Plane API *capabilities*.

Improved documentation.

## 1.0.O - 2025-05-30

Initial release