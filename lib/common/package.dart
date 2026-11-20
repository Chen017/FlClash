import 'dart:io';

import 'package:package_info_plus/package_info_plus.dart';

import 'common.dart';

extension PackageInfoExtension on PackageInfo {
  String get updateVersion =>
      version.contains('-') ? version : '$version+$buildNumber';

  String get ua => [
    '$appName/v$version',
    'clash-verge',
    'Platform/${Platform.operatingSystem}',
  ].join(' ');
}

int compareVersions(String version1, String version2) {
  final parsed1 = _parseVersion(version1);
  final parsed2 = _parseVersion(version2);
  for (var i = 0; i < 3; i++) {
    if (parsed1.core[i] != parsed2.core[i]) {
      return parsed1.core[i].compareTo(parsed2.core[i]);
    }
  }
  if (parsed1.personalRevision != null || parsed2.personalRevision != null) {
    final rev1 = parsed1.personalRevision ?? 0;
    final rev2 = parsed2.personalRevision ?? 0;
    return rev1.compareTo(rev2);
  }
  return parsed1.build.compareTo(parsed2.build);
}

({List<int> core, int? personalRevision, int build}) _parseVersion(
  String raw,
) {
  final normalized = raw.startsWith('v') ? raw.substring(1) : raw;
  final plusParts = normalized.split('+');
  final build = plusParts.length > 1 ? int.tryParse(plusParts[1]) ?? 0 : 0;
  final dashParts = plusParts[0].split('-');
  final coreParts = dashParts[0].split('.');
  final core = [
    int.parse(coreParts[0]),
    coreParts.length > 1 ? int.parse(coreParts[1]) : 0,
    coreParts.length > 2 ? int.parse(coreParts[2]) : 0,
  ];
  int? personalRevision;
  if (dashParts.length > 1) {
    final suffix = dashParts.sublist(1).join('-');
    final match = RegExp(r'^personal(?:\.(\d+))?$').firstMatch(suffix);
    if (match != null) {
      personalRevision = match.group(1) != null ? int.parse(match.group(1)!) : 1;
    }
  }
  return (core: core, personalRevision: personalRevision, build: build);
}

const releaseNotesBeginMarker = '<!-- flclash:changelog:begin -->';
const releaseNotesEndMarker = '<!-- flclash:changelog:end -->';

List<String> parseReleaseBody(String? body) {
  if (body == null) return [];
  final regex = RegExp(r'^[ \t]*-[ \t]+(.*)$', multiLine: true);
  return regex
      .allMatches(scopeReleaseNotes(body))
      .map((match) => match.group(1)?.trim() ?? '')
      .where((item) => item.isNotEmpty)
      .toList();
}

String scopeReleaseNotes(String body) {
  final begin = body.indexOf(releaseNotesBeginMarker);
  if (begin < 0) return body;
  final start = begin + releaseNotesBeginMarker.length;
  final end = body.indexOf(releaseNotesEndMarker, start);
  return end < 0 ? body.substring(start) : body.substring(start, end);
}
