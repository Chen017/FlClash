import 'package:fl_clash/common/package.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

void main() {
  final installed = PackageInfo(
    appName: 'FlClash',
    packageName: 'io.github.chen017.flclash',
    version: '0.9.3',
    buildNumber: '7',
  );

  test('a core-only release updates once without an endless update prompt', () {
    expect(compareVersions('0.9.3+8', installed.updateVersion), greaterThan(0));
    expect(compareVersions('0.9.3+7', installed.updateVersion), 0);
    expect(compareVersions('0.9.3+6', installed.updateVersion), lessThan(0));
    expect(compareVersions('0.9.4+8', installed.updateVersion), greaterThan(0));
  });
}
