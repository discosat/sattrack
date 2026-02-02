{
  description = "A very basic flake";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
  };
  

  outputs = { self, nixpkgs }: 

  let 
  pypacks = p: with p; [
          numpy 
          skyfield 
          fastapi 
          uvicorn 
          requests 
          pydantic
          websockets
  ];
  in

  {
    packages.x86_64-linux.hello = nixpkgs.legacyPackages.x86_64-linux.hello;

    devShells.x86_64-linux.default =
    with import nixpkgs {system = "x86_64-linux";};

    pkgs.mkShell { 

      packages = with pkgs; [  
        (python3.withPackages pypacks)
      ];

    };

  };
}
