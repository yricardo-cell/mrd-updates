import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'services/auth_service.dart';
import 'config/theme.dart';
import 'screens/login_screen.dart';
import 'screens/main_shell.dart';
import 'screens/scanner_screen.dart';
import 'screens/incidencias/incidencias_screen.dart';
import 'screens/herramientas/herramientas_screen.dart';
import 'screens/obras/obras_screen.dart';
import 'screens/trabajadores/trabajadores_screen.dart';
import 'screens/vehiculos/vehiculos_screen.dart';
import 'screens/materiales/materiales_screen.dart';
import 'screens/epis/epis_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Barra de sistema transparente
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
  ));
  // Solo orientación vertical
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp, DeviceOrientation.portraitDown,
  ]);

  runApp(const MrdApp());
}

class MrdApp extends StatelessWidget {
  const MrdApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthService.instance),
      ],
      child: MaterialApp(
        title: 'MRD TOOL CONTROL',
        debugShowCheckedModeBanner: false,
        theme: MrdTheme.light(),
        darkTheme: MrdTheme.dark(),
        themeMode: ThemeMode.dark,
        home: const _SplashGate(),
        routes: {
          '/login':          (_) => const LoginScreen(),
          '/home':           (_) => const MainShell(),
          '/scanner':        (_) => const ScannerScreen(),
          '/herramientas':   (_) => const HerramientasScreen(),
          '/obras':          (_) => const ObrasScreen(),
          '/trabajadores':   (_) => const TrabajadoresScreen(),
          '/vehiculos':      (_) => const VehiculosScreen(),
          '/materiales':     (_) => const MaterialesScreen(),
          '/epis':           (_) => const EpisScreen(),
          '/incidencias':    (_) => const IncidenciasScreen(),
          '/incidencias/nueva': (_) => const NuevaIncidenciaScreen(),
        },
      ),
    );
  }
}

class _SplashGate extends StatefulWidget {
  const _SplashGate();
  @override
  State<_SplashGate> createState() => _SplashGateState();
}

class _SplashGateState extends State<_SplashGate> {
  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    await Future.delayed(const Duration(milliseconds: 600));
    if (!mounted) return;
    final loggedIn = await context.read<AuthService>().init();
    if (!mounted) return;
    Navigator.pushReplacementNamed(context, loggedIn ? '/home' : '/login');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: MrdTheme.bgDark,
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 100, height: 100,
              decoration: BoxDecoration(
                color: MrdTheme.primary,
                borderRadius: BorderRadius.circular(24),
              ),
              child: const Icon(Icons.construction, color: MrdTheme.secondary, size: 60),
            ),
            const SizedBox(height: 24),
            const Text('MRD TOOL CONTROL',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white)),
            const SizedBox(height: 8),
            const Text('v2.1.0 — Cargando...',
              style: TextStyle(fontSize: 13, color: Colors.white38)),
            const SizedBox(height: 32),
            const CircularProgressIndicator(color: MrdTheme.secondary, strokeWidth: 2),
          ],
        ),
      ),
    );
  }
}
